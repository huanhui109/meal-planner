"""按缺口补全候选池 —— 「禁止杜撰」的唯一定义化例外。

饭决的底线从 v1.0 起就是：**不得编造不存在的菜名与做法**。候选池只装现实中
确实能做的菜。这条底线不因为本次改动而放宽。

但底线的实现方式有一个缺口：用户常常只描述**大致需求**（「想吃点暖胃的汤」、
「来点下饭的」），点名不出具体菜。如果候选池在那类需求上覆盖不足，用户会得到
「做不了」—— 而现实里当然做得了，只是我们的池子里没有。

本模块是那条底线的**受控例外**：

    触发  —— 用户只描述需求、没有点名具体菜；现有候选不足；AI 判定值得补。
    生成  —— 默认 4 道（3-5 道）**现实中存在**的菜：真实菜名 + 现实做法 + 现实依据。
    写入  —— 落库到 ``recipe``，带 ``reality_basis`` / ``generated_for`` 证据。
    拒绝  —— 只要任一项说不出依据，整条丢弃，绝不「先写进去再说」。

契约真源已抽到 ``dish_candidate_skill.py``（对应
``skills/fandecide-candidates/SKILL.md`` + ``contract.json``）：数量口径、prompt、
system contract、字段结构与「不得杜撰」校验都在那里，本模块只负责**落库裁决**
与面向老链路的 ``GenerateOutcome`` 适配。同步端点 ``POST /api/assistant/candidates``
走 ``dish_candidate_service.py``，与本模块共用同一份契约和同一个写入函数。

与 ``recipe_enrich_service`` 的 ``EnrichKind.EXPAND`` 的分工：
  * EXPAND 是**离线无人值守**的补缺口（凌晨跑、按品类分布），不针对某个用户；
  * 本模块是**在线、针对一次具体请求**的补全，因此必须更严格：
    有用户原话、有数量上限、有名额校验、并且失败时明确告知用户「没补到」，
    而不是静默产出一个和需求无关的方案。

反杜撰在这里落成**可执行的检查**，而不是提示词里的一句请求：

1. 菜名必须是中文常见菜名（长度、字符集、不是句子、不含量词/价格/营销词）。
2. 必须给出非虚构的 ``reality_basis``（依据），且长度下限可校验。
3. 做法必须是可执行步骤，不能是「适量」「若干」堆出来的空话，也不能是
   「买一份现成的」这类逃避。
4. 与库内已有菜名去重，不允许改写已有菜名充数。
5. 写入前后都用现有规则（``guess_is_dish`` / ``sanitize`` / ``clean_steps``）
   再收敛一次，任何一步不过就丢掉那一道。

AI 只负责「提名 + 依据 + 做法」，**能不能入池仍由服务端决定**。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recipe import EnrichKind, Recipe, RecipeEnrichLog
from app.services import dish_candidate_skill as skill
from app.services.dish_rules import (
    category_from_pool_cuisine,
    guess_dish_category,
    guess_is_dish,
    normalize_dish_category,
)

# Re-export the contract as the single source of truth. Old imports (tests and
# callers) keep working; nothing here may redefine these numbers or validators.
MAX_GENERATED = skill.MAX_COUNT                 # 5：一次最多补 5 道
DEFAULT_GENERATED = skill.DEFAULT_COUNT        # 4：默认请求 4 道
MIN_GENERATED = skill.MIN_COUNT                # 3
NAME_MIN, NAME_MAX = skill.NAME_MIN, skill.NAME_MAX
BASIS_MIN, BASIS_MAX = skill.BASIS_MIN, skill.BASIS_MAX
WANT_MAX = skill.WANT_MAX
MAX_EXCLUDE_NAMES = skill.MAX_EXCLUDE_NAMES
DEFAULT_TIMEOUT_SECONDS = skill.DEFAULT_TIMEOUT_SECONDS
valid_dish_name = skill.valid_dish_name
valid_basis = skill.valid_basis
valid_steps = skill.valid_steps
GeneratedDish = skill.CandidateDish


@dataclass
class GenerateOutcome:
    wanted: str
    written: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    reason: str = ""
    degraded: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.written)

    def as_dict(self) -> dict:
        return {
            "wanted": self.wanted, "written": list(self.written),
            "rejected": list(self.rejected), "reason": self.reason,
            "degraded": self.degraded,
        }


def parse_dishes(payload: Any) -> list[dict]:
    """Legacy helper: accept only the documented shape; never guess around a broken reply."""
    if not isinstance(payload, dict):
        return []
    dishes = payload.get("dishes")
    return [item for item in dishes if isinstance(item, dict)] if isinstance(dishes, list) else []


class DishGenerationService:
    """Online, request-scoped candidate gap fill. Strict by design.

    The model reply is parsed by ``dish_candidate_skill.parse_reply``; the server
    alone decides which of its nominations become real ``recipe`` rows.
    """

    def __init__(
        self, db: AsyncSession, model_client, *, model: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.db = db
        self.model = model_client
        self.model_id = model
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------ prompt

    @staticmethod
    def prompt(
        want: str, *, context: dict, exclude: list[str], named: str = "",
        count: int = DEFAULT_GENERATED,
    ) -> str:
        """Delegate to the skill contract: one short instruction + one JSON line."""
        return skill.build_prompt(
            want, context=context, exclude_names=exclude,
            count=count, named_dish=named,
        )

    # ------------------------------------------------------------------ generate

    async def generate(
        self, want: str, *, context: dict, named: str = "",
        count: int = DEFAULT_GENERATED,
    ) -> GenerateOutcome:
        """Ask the model for real dishes, then let the SERVER decide what lands.

        ``named`` is set when the user pointed at a specific dish we cannot serve
        yet (e.g. 「西蓝花」 when the pool has no broccoli dish at all). The model
        is then asked for dishes built around that ingredient, so the result is
        still a real, cookable dish rather than a renamed invention.
        """
        outcome = GenerateOutcome(wanted=(want or "").strip()[:WANT_MAX])
        if not outcome.wanted and not named:
            outcome.reason = "需求描述为空"
            return outcome

        existing = {
            name for (name,) in (await self.db.execute(select(Recipe.name))).all()
        }
        try:
            # 「交给 AI 调整」的补全同样不能等满外层 90s：短超时后直接降级，
            # 请求继续用现有候选安排，原方案不变。
            envelope = await asyncio.wait_for(
                self.model.chat(
                    self.prompt(
                        outcome.wanted, context=context,
                        exclude=sorted(existing)[:MAX_EXCLUDE_NAMES],
                        named=named, count=count,
                    ),
                    model=self.model_id,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            outcome.degraded = True
            outcome.reason = "候选补全请求超时，本次没有补全候选"
            return outcome
        if not envelope.ok:
            outcome.degraded = True
            outcome.reason = envelope.message or "模型暂时不可用，本次没有补全候选"
            return outcome

        try:
            dishes = skill.parse_reply(envelope.text or "", count=count)
        except skill.CandidateSkillError as exc:
            outcome.reason = f"模型没有返回合法候选，本次没有补全（{exc}）"
            return outcome
        if not dishes:
            outcome.reason = "模型给的候选都没通过校验（依据或做法不完整），本次没有补全"
            return outcome

        for dish in dishes:
            if self._normalize(dish.name) in {self._normalize(n) for n in existing}:
                outcome.rejected.append(f"{dish.name}（与已有菜重复）")
                continue
            created = await self.write_dish(dish, outcome.wanted, outcome)
            if created is None:
                continue
            existing.add(dish.name)
            outcome.written.append(dish.name)

        if not outcome.written and not outcome.reason:
            outcome.reason = "模型给的候选都没通过校验（依据或做法不完整），本次没有补全"
        return outcome

    # ------------------------------------------------------------------ persistence

    async def write_dish(
        self, dish: skill.CandidateDish, want: str, outcome: GenerateOutcome,
    ) -> Optional[Recipe]:
        """Persist one validated dish, with its evidence. Never writes a partial row.

        Public on purpose: ``DishCandidateService`` (the synchronous low-latency
        endpoint) reuses this exact admission path, so both entry points can never
        drift on what "allowed into the pool" means.
        """
        recipe = Recipe(**dish.to_recipe_kwargs(want))
        # Category: prefer the model's own cuisine mapping, then the rule engine.
        recipe.dish_category_code = (
            category_from_pool_cuisine(dish.cuisine) if dish.cuisine else "other"
        )
        if recipe.dish_category_code == "other":
            recipe.dish_category_code = normalize_dish_category(
                guess_dish_category(recipe, ignore_explicit=True)
            )
        # A dish that the project's own rule calls "not a dish" must not enter the
        # pool, even with a nice-looking basis. Same standard as the rest of 饭决.
        if not guess_is_dish(recipe):
            outcome.rejected.append(f"{dish.name}（规则判定不像一道菜）")
            return None
        self.db.add(recipe)
        await self.db.flush()
        self.db.add(RecipeEnrichLog(
            recipe_id=recipe.id, dish_name=dish.name, kind=EnrichKind.EXPAND,
            status="ok", provider=self.model_id or "workbuddy",
            fields="new_recipe,reality_basis", message=f"按需求补全：{want[:80]}",
        ))
        await self.db.flush()
        return recipe

    # Backward-compatible alias for anything still calling the private helper.
    _write = write_dish

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _strip_fence(text: str) -> str:
        return skill.strip_fence(text)

    @staticmethod
    def _normalize(name: str) -> str:
        return skill.normalize_name(name)

    @staticmethod
    def _coerce(item: dict) -> Optional[GeneratedDish]:
        return skill.coerce_candidate(item)
