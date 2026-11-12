"""饭决 · 候选菜品技能的**应用内低延迟调用入口**。

规格：``skills/fandecide-candidates/SKILL.md``；
契约：``dish_candidate_skill.py``；
HTTP：``POST /api/assistant/candidates``。

与老的「交给 AI 调整」链路（start → poll → 选菜技能）的关系：

* 那条链路负责**组合一餐**，会调选菜技能；候选不足时由
  ``DishGenerationService`` 按本契约补 3-5 道真实菜再继续。
* 本服务提供**单跳通道**：应用只想要候选时，一次模型请求直接拿到结构一致的
  3-5 道菜，不需要建任务、不需要轮询、不需要第二次模型调用。

两者共用同一份契约、同一套校验、同一个写库裁决函数，所以口径不可能漂移。

低延迟由四层保证：单次模型请求（不重试/不多轮）、短 prompt、服务端
``asyncio.wait_for`` 硬超时、模型侧 ``max_tokens``/``temperature`` 约束。
任何失败都**直接降级返回空候选 + 一句原因**，不追问、不展开、不改动任何方案。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recipe import Recipe
from app.services import dish_candidate_skill as skill
from app.services.dish_generation_service import DishGenerationService, GenerateOutcome

# 单次调用的硬超时（秒），与「交给 AI 调整」的补全共用同一口径。
DEFAULT_TIMEOUT_SECONDS = skill.DEFAULT_TIMEOUT_SECONDS

# 只有这些已校验过的条件会进入数据段；其余字段一律丢弃，避免把任意输入
# 塞进 prompt（数据段里的文字永远只是数据，但先收窄总是更稳）。
_CONTEXT_KEYS = (
    "meal_slot", "servings", "max_minutes", "budget", "max_spice",
    "avoid", "vegetarian", "light", "use_fridge", "avoid_recent", "dish_category",
)


def safe_context(raw: Any) -> dict:
    """Whitelist + truncate: a small, predictable data segment."""
    if not isinstance(raw, dict):
        return {}
    result: dict = {}
    for key in _CONTEXT_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None or isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:50]
        elif isinstance(value, list):
            result[key] = [
                str(item)[:50] for item in value[:30]
                if isinstance(item, (str, int, float))
            ]
    return result


@dataclass
class CandidateResult:
    skill: str = skill.SKILL_NAME
    count: int = 0
    candidates: list[dict] = field(default_factory=list)
    persisted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    reason: str = ""
    degraded: bool = False

    def as_dict(self) -> dict:
        return {
            "skill": self.skill,
            "count": self.count,
            "candidates": list(self.candidates),
            "persisted": list(self.persisted),
            "rejected": list(self.rejected),
            "reason": self.reason,
            "degraded": self.degraded,
        }


class DishCandidateService:
    """One request, one model call, one validated candidate list."""

    def __init__(
        self,
        db: AsyncSession,
        model_client,
        *,
        model: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.db = db
        self.model = model_client
        self.model_id = model
        self.timeout_seconds = timeout_seconds

    async def generate(
        self,
        description: str,
        *,
        context: dict | None = None,
        count: int = skill.DEFAULT_COUNT,
        exclude_names: list[str] | None = None,
        named_dish: str = "",
        persist: bool = False,
    ) -> CandidateResult:
        """Return 3-5 structured candidates; optionally admit them into recipe.

        ``persist=True`` does NOT relax anything: the same ``write_dish`` used by
        the gap-fill path performs dedup, ``guess_is_dish`` and the audit row.
        """
        result = CandidateResult()
        wanted = (description or "").strip()[:skill.MAX_DESCRIPTION]
        if not wanted and not (named_dish or "").strip():
            result.reason = "描述为空"
            result.degraded = True
            return result
        wanted_count = skill.normalize_count(count)

        existing = {
            name for (name,) in (await self.db.execute(select(Recipe.name))).all()
        }
        names = sorted(existing)[:skill.MAX_EXCLUDE_NAMES]
        if exclude_names:
            names = list(dict.fromkeys([*names, *exclude_names]))[:skill.MAX_EXCLUDE_NAMES]

        prompt = skill.build_prompt(
            wanted,
            context=safe_context(context),
            exclude_names=names,
            count=wanted_count,
            named_dish=(named_dish or "")[:50],
        )
        try:
            envelope = await asyncio.wait_for(
                self.model.chat(prompt, model=self.model_id),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            result.reason = "候选请求超时，本次没有返回候选"
            result.degraded = True
            return result
        except Exception:  # noqa: BLE001 - degrade, never break the caller
            result.reason = "模型暂时不可用，本次没有返回候选"
            result.degraded = True
            return result
        if envelope is None or not getattr(envelope, "ok", False):
            result.reason = getattr(envelope, "message", "") or "模型暂时不可用，本次没有返回候选"
            result.degraded = True
            return result

        try:
            dishes = skill.parse_reply(envelope.text or "", count=wanted_count)
        except skill.CandidateSkillError as exc:
            result.reason = f"模型没有返回合法候选（{exc}）"
            result.degraded = True
            return result
        if not dishes:
            result.reason = "模型给的候选都没通过校验，本次没有返回候选"
            result.degraded = True
            return result

        if persist:
            writer = DishGenerationService(self.db, self.model, model=self.model_id)
            outcome = GenerateOutcome(wanted=wanted)
            known = {skill.normalize_name(name) for name in existing}
            try:
                for dish in dishes:
                    if skill.normalize_name(dish.name) in known:
                        result.rejected.append(f"{dish.name}（与已有菜重复）")
                        continue
                    before = len(outcome.rejected)
                    recipe = await writer.write_dish(dish, wanted, outcome)
                    if recipe is None:
                        result.rejected.extend(outcome.rejected[before:])
                        continue
                    known.add(skill.normalize_name(dish.name))
                    dish.recipe_id = recipe.id
                    dish.key = f"recipe:{recipe.id}"
                    result.persisted.append(dish.name)
            except Exception:  # noqa: BLE001 - a persistence hiccup must not lose the reply
                result.reason = "候选已返回，但本次没有写入候选池"

        result.candidates = [
            {**dish.as_dict(), **({"recipe_id": dish.recipe_id, "key": dish.key} if dish.recipe_id else {})}
            for dish in dishes
        ]
        result.count = len(result.candidates)
        return result
