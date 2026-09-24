"""菜品富集 —— 兜底大模型的岗位重定义

先说清楚分工, 这是这个模块存在的全部理由:

    Laya (开源 System One)  = 实时**决策岗**。一次前向传播把口语诉求变成结构化意图,
                              200ms 返回, 只能干"判断"这种轻活。
    兜底大模型 (FallbackChain) = 离线**生产岗**。定时补菜品、写做法、补缺失字段。
                              慢、要花钱、输出不稳, 但能干"创造内容"这种重活。

这两者不是主备关系。以前所有模型都往决策链路上堆, 结果 2s 响应时间守不住、
离线双端同构也没法复现。现在把它们彻底分开: **模型只生产数据, 规则只做决策。**

三条硬纪律 (和 weather_service / system_one_service 一致):
    1. 失败静默降级 —— 定时任务跑挂了最多是字段还缺着, 绝不能把异常抛给调用方
    2. 输出必须校验后才落库 —— LLM 会给 spice_level=9、给不存在的枚举值
    3. 人工校对过的数据不许覆盖 —— enrich_source=manual 的菜直接跳过

产出全部写 recipe_enrich_log, 无人值守的任务必须能事后说清"补了什么、为什么没补成"。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DishEnrichSettings, Settings, get_settings
from app.llm.fallback_chain import FallbackChain, build_fallback_chain
from app.models.recipe import (
    CookTool,
    DishSeason,
    EnrichKind,
    EnrichSource,
    EnrichStatus,
    MeatType,
    Recipe,
    RecipeEnrichLog,
)
from app.services.dish_rules import (
    guess_is_dish,
    guess_meal_slots,
    guess_meat_type,
    guess_minutes,
    guess_season,
    guess_tools,
    is_dish_flag,
    to_json,
)

logger = logging.getLogger(__name__)

# 观测用的分桶。「饮品 / 甜品」单独计数是因为它们占 54 道非菜里的 42 道(78%),
# 而且边界最模糊 —— 将来规则要是判错, 几乎必然出在这两类, 混在一起看不出来。
_NON_DISH_BUCKETS = ("饮品", "甜品")

# 允许 LLM 填的字段白名单。不在名单里的一律丢弃 —— 宁可少填, 不许它乱改结构。
FILLABLE_FIELDS = (
    "cook_minutes", "difficulty", "meal_slots", "meat_type", "tools",
    "season", "category", "cuisine", "main_ingredient", "tags",
    "flavor_tags", "spice_level", "is_light", "cover_text",
)

MEAL_SLOT_KEYS = ("breakfast", "lunch", "dinner", "late_night")


# ------------------------------------------------------------------ 规则兜底

DEFAULT_MINUTES = 20


def rule_patch(recipe: Recipe) -> Dict[str, Any]:
    """规则能给的所有值。LLM 不可用时的兜底, 也是"先填个大概"的那一层

    规则本身在 dish_rules.py, 和回填脚本共用一份 —— 两处各写一套必然漂移。
    """
    patch: Dict[str, Any] = {}
    if not recipe.cook_minutes:
        minutes = guess_minutes(recipe)
        if minutes:
            patch["cook_minutes"] = minutes
    if not recipe.meat_type:
        meat = guess_meat_type(recipe)
        if meat:
            patch["meat_type"] = meat
    if not recipe.meal_slots:
        slots = to_json(guess_meal_slots(recipe))
        if slots:
            patch["meal_slots"] = slots
    if not recipe.tools:
        tools = to_json(guess_tools(recipe))
        if tools:
            patch["tools"] = tools
    if not recipe.season:
        season = to_json(guess_season(recipe))
        if season:
            patch["season"] = season
    return patch


# ------------------------------------------------------------------ 结果

@dataclass
class EnrichOutcome:
    """一次富集批次的结果"""

    kind: str = ""
    scanned: int = 0
    written: int = 0
    failed: int = 0
    skipped: int = 0
    provider: str = ""
    dishes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    degraded: bool = False
    # 观测口径: 规则判定"不是一道菜"但实际仍按 is_dish=1 放行的那批(本期不拦截)
    non_dish: List[str] = field(default_factory=list)
    non_dish_kinds: Dict[str, int] = field(default_factory=dict)

    @property
    def non_dish_ratio(self) -> float:
        """不一致率 = 判非菜 / 扫描数。没有历史基线, 只看趋势"""
        return len(self.non_dish) / self.scanned if self.scanned else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "scanned": self.scanned,
            "written": self.written,
            "failed": self.failed,
            "skipped": self.skipped,
            "provider": self.provider,
            "dishes": self.dishes[:20],
            "errors": self.errors[:5],
            "degraded": self.degraded,
            "non_dish": self.non_dish[:20],
            "non_dish_kinds": self.non_dish_kinds,
            "non_dish_ratio": round(self.non_dish_ratio, 4),
        }


# ------------------------------------------------------------------ 校验

def _non_dish_bucket(recipe: Recipe) -> str:
    """判非菜的条目归到哪个桶。只用于观测计数, 不参与任何判定"""
    cuisine = (getattr(recipe, "cuisine", None) or "").strip()
    return cuisine if cuisine in _NON_DISH_BUCKETS else "其他"


def _clean_str_list(raw: Any, allowed: Sequence[str], limit: int = 8) -> Optional[List[str]]:
    """把 LLM 给的数组收敛到枚举内。全都不合法时返回 None(不写), 而不是写个空数组"""
    if not isinstance(raw, list):
        return None
    out: List[str] = []
    for item in raw:
        text = str(item).strip().lower()
        if text in allowed and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out or None


def _clean_int(raw: Any, low: int, high: int) -> Optional[int]:
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


def _clean_text(raw: Any, limit: int) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or len(text) > limit:
        return None
    return text


def sanitize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 的输出收敛成能安全落库的值

    校验规则和数据字典严格对齐: 辣度 0-4、难度 1-5、时间 5-240 分钟、
    枚举字段必须在 constants 里。越界的一律丢弃而不是截断 —— 截断等于替模型编数据。
    """
    out: Dict[str, Any] = {}

    minutes = _clean_int(payload.get("cook_minutes"), 5, 240)
    if minutes is not None:
        out["cook_minutes"] = minutes

    difficulty = _clean_int(payload.get("difficulty"), 1, 5)
    if difficulty is not None:
        out["difficulty"] = difficulty

    spice = _clean_int(payload.get("spice_level"), 0, 4)
    if spice is not None:
        out["spice_level"] = spice

    if isinstance(payload.get("is_light"), bool):
        out["is_light"] = payload["is_light"]

    slots = _clean_str_list(payload.get("meal_slots"), MEAL_SLOT_KEYS, limit=4)
    if slots:
        out["meal_slots"] = json.dumps(slots, ensure_ascii=False)

    meat = str(payload.get("meat_type") or "").strip().lower()
    if meat in MeatType.ALL:
        out["meat_type"] = meat

    tools = _clean_str_list(payload.get("tools"), CookTool.ALL)
    if tools:
        out["tools"] = json.dumps(tools, ensure_ascii=False)

    season = _clean_str_list(payload.get("season"), DishSeason.ALL, limit=4)
    if season:
        out["season"] = json.dumps(season, ensure_ascii=False)

    for key, limit in (("category", 20), ("cuisine", 20),
                       ("main_ingredient", 20), ("cover_text", 20)):
        text = _clean_text(payload.get(key), limit)
        if text:
            out[key] = text

    for key in ("tags", "flavor_tags"):
        raw = payload.get(key)
        if isinstance(raw, list):
            items = [str(x).strip() for x in raw if str(x).strip()][:8]
            if items:
                out[key] = json.dumps(items, ensure_ascii=False)

    return {k: v for k, v in out.items() if k in FILLABLE_FIELDS}


def clean_steps(payload: Dict[str, Any]) -> Dict[str, Any]:
    """步骤单独校验: 极简做法 3-5 步每步 <=20 字, 详细做法不限但要有内容"""
    out: Dict[str, Any] = {}
    quick = payload.get("quick_steps")
    if isinstance(quick, list):
        steps = [str(s).strip() for s in quick if str(s).strip() and len(str(s).strip()) <= 20]
        if 3 <= len(steps) <= 5:
            out["quick_steps"] = json.dumps(steps, ensure_ascii=False)
    detail = payload.get("steps")
    if isinstance(detail, list):
        lines = [str(s).strip() for s in detail if str(s).strip()]
        if 2 <= len(lines) <= 12:
            out["steps"] = "\n".join(lines)
    elif isinstance(detail, str) and len(detail.strip()) >= 20:
        out["steps"] = detail.strip()
    return out


# ------------------------------------------------------------------ 服务

class RecipeEnrichService:
    """定时给菜品补数据 / 写做法 / 补新菜"""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        llm: Optional[FallbackChain] = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.cfg: DishEnrichSettings = self.settings.dish_enrich
        self._llm = llm
        self.last_error: str = ""

    @property
    def usable(self) -> bool:
        """没开 / 没配任何 provider 时不打电话"""
        if not self.cfg.enabled:
            return False
        try:
            return bool(self.llm.clients)
        except Exception:  # noqa: BLE001
            return False

    @property
    def llm(self) -> FallbackChain:
        if self._llm is None:
            self._llm = build_fallback_chain(self.settings)
        return self._llm

    # ---------------------------------------------------------------- 挑人

    async def pick_gaps(self, kind: str, limit: int) -> List[Recipe]:
        """挑出下一批该补的菜 —— 缺口最大的排前面"""
        stmt = select(Recipe)
        if self.cfg.respect_manual:
            stmt = stmt.where(
                (Recipe.enrich_source != EnrichSource.MANUAL)
                | (Recipe.enrich_source.is_(None))
            )
        if kind == EnrichKind.STEPS:
            stmt = stmt.where(
                (Recipe.quick_steps.is_(None))
                | (Recipe.quick_steps == "")
                | (Recipe.steps.is_(None))
                | (Recipe.steps == "")
            )
        else:
            stmt = stmt.where(Recipe.enrich_status != EnrichStatus.DONE)
        stmt = stmt.order_by(Recipe.enrich_status, Recipe.id).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_gaps(self) -> Dict[str, int]:
        """各维度还缺多少。给 /api/recipes/gaps 看, 也是定时任务"要不要跑"的依据"""
        rows = (await self.session.execute(
            select(
                Recipe.id, Recipe.cook_minutes, Recipe.category, Recipe.meal_slots,
                Recipe.meat_type, Recipe.tools, Recipe.season, Recipe.quick_steps,
                Recipe.steps, Recipe.tags, Recipe.enrich_status,
            )
        )).all()
        total = len(rows)
        miss = {
            "total": total,
            "cook_minutes": sum(1 for r in rows if not r.cook_minutes),
            "meal_slots": sum(1 for r in rows if not r.meal_slots),
            "meat_type": sum(1 for r in rows if not r.meat_type),
            "tools": sum(1 for r in rows if not r.tools),
            "season": sum(1 for r in rows if not r.season),
            "quick_steps": sum(1 for r in rows if not r.quick_steps),
            "steps": sum(1 for r in rows if not r.steps),
            "tags": sum(1 for r in rows if not r.tags or r.tags in ("", "[]")),
            "category": sum(1 for r in rows if not r.category),
            "pending": sum(1 for r in rows if r.enrich_status != EnrichStatus.DONE),
        }
        return miss

    # ---------------------------------------------------------------- 跑批

    async def enrich_fields(self, limit: Optional[int] = None) -> EnrichOutcome:
        """补决策/场景字段"""
        return await self._run(EnrichKind.FIELDS, limit or self.cfg.batch_limit)

    async def enrich_steps(self, limit: Optional[int] = None) -> EnrichOutcome:
        """写做菜步骤"""
        return await self._run(EnrichKind.STEPS, limit or self.cfg.batch_limit)

    async def _run(self, kind: str, limit: int) -> EnrichOutcome:
        out = EnrichOutcome(kind=kind)
        recipes = await self.pick_gaps(kind, limit)
        out.scanned = len(recipes)
        if not recipes:
            return out
        if not self.usable:
            # 模型不可用不等于什么都不做 —— 规则那一层是免费的、确定性的, 先把洞堵上。
            # cook_minutes 缺 93% 的时候, 规则的估值也比"全是 30 分钟"强得多。
            out.degraded = True
            out.errors.append("dish_enrich 未启用或 LLM 链为空, 仅按规则兜底")
            for recipe in recipes:
                written = self._apply_patch(recipe, rule_patch(recipe))
                if not written:
                    # 规则也无能为力的那部分: 记一笔, 说明"不是没跑, 是跑不出结果"
                    out.skipped += 1
                    continue
                recipe.enriched_at = datetime.now()
                recipe.enrich_status = (
                    EnrichStatus.DONE if self._is_complete(recipe) else EnrichStatus.PARTIAL
                )
                if recipe.enrich_source != EnrichSource.MANUAL:
                    recipe.enrich_source = EnrichSource.RULE
                self._observe_is_dish(recipe, kind, out, "rule")
                self._log(recipe, kind, "ok", "rule", ",".join(written))
                out.written += 1
                out.dishes.append(recipe.name)
            return out

        for recipe in recipes:
            try:
                payload = await self._ask(kind, recipe)
                written = self._apply(kind, recipe, payload)
            except Exception as exc:  # noqa: BLE001 —— 单道失败不影响整批
                written = []
                out.errors.append(f"{recipe.name}: {exc}")
                self._log(recipe, kind, "failed", "", str(exc)[:400])
                recipe.enrich_status = EnrichStatus.FAILED
                out.failed += 1
                continue

            if written:
                recipe.enriched_at = datetime.now()
                recipe.enrich_status = (
                    EnrichStatus.DONE if self._is_complete(recipe) else EnrichStatus.PARTIAL
                )
                # cuisine / category 是 LLM 可写的字段, 写完这道菜"是不是一道菜"
                # 的结论可能变 —— 所以观测放在写库之后
                self._observe_is_dish(recipe, kind, out, self._provider_name())
                self._log(recipe, kind, "ok", self._provider_name(), ",".join(written))
                out.written += 1
                out.dishes.append(recipe.name)
            else:
                self._log(recipe, kind, "skipped", self._provider_name(), "返回不可用")
                out.skipped += 1
        return out

    # ---------------------------------------------------------------- 提问

    async def _ask(self, kind: str, recipe: Recipe) -> Dict[str, Any]:
        """问大模型。输出是 JSON, 但要做好它返回散文的准备"""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(kind, recipe)},
        ]
        raw = await self.llm.chat(
            messages,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
        )
        return _parse_json(raw)

    @staticmethod
    def _apply_patch(recipe: Recipe, patch: Dict[str, Any]) -> List[str]:
        """直接写入一组已经可信的字段(规则产出, 不需要再校验)"""
        written: List[str] = []
        for key, value in patch.items():
            if value is None:
                continue
            setattr(recipe, key, value)
            written.append(key)
        return written

    @staticmethod
    def _apply(kind: str, recipe: Recipe, payload: Dict[str, Any]) -> List[str]:
        """把校验过的值写进 ORM。只填**当前为空**的字段, 已有的不动"""
        written: List[str] = []
        if kind == EnrichKind.STEPS:
            for key, value in clean_steps(payload).items():
                if not getattr(recipe, key):
                    setattr(recipe, key, value)
                    written.append(key)
            if written and not recipe.steps_source:
                recipe.steps_source = EnrichSource.LLM
            return written

        for key, value in sanitize(payload).items():
            current = getattr(recipe, key, None)
            # 0 / False 是有效值, 不能当"缺失" —— 这个坑在 intent_service 里踩过
            empty = current is None or current == "" or current == "[]"
            if key in ("spice_level", "is_light"):
                empty = False if key == "is_light" else (current is None)
            if not empty:
                continue
            setattr(recipe, key, value)
            written.append(key)
        if written and recipe.enrich_source != EnrichSource.MANUAL:
            recipe.enrich_source = EnrichSource.LLM
        return written

    @staticmethod
    def _is_complete(recipe: Recipe) -> bool:
        """决策所需的字段是否齐了。齐了就不再占用定时任务的名额"""
        return bool(
            recipe.cook_minutes
            and recipe.category
            and recipe.main_ingredient
            and recipe.meat_type
            and recipe.meal_slots
            and (recipe.quick_steps or recipe.steps)
        )

    def _observe_is_dish(self, recipe: Recipe, kind: str, out: EnrichOutcome,
                         provider: str = "") -> None:
        """规则判一道菜"是不是一道菜", 判成非菜时**只观测, 不改值**

        为什么不做拦截: 这个任务是凌晨 03:30 无人值守跑的。自动置 0 的误杀是静默且
        不可逆的 —— 一道正常的菜被判成非菜, 用户永远吃不到它, 而日志里只会多一行
        "正常"。反过来放行, 最坏是候选池多一道奶茶。这条和 decision_service 里
        「少一道菜是事故, 多一道奶茶只是尴尬」是同一个取舍。

        所以这里三件事: 记日志、写一行 enrich 流水的趋势证据、计入本批次计数。
        等观测数据攒够了, 再决定要不要让规则有牙齿。
        """
        guessed = guess_is_dish(recipe)
        stored = is_dish_flag(getattr(recipe, "is_dish", None))
        if guessed == stored:
            # 那 54 道已置 0 的非菜也走这条路, 判 0 存 0 = 一致, 不该刷屏
            return

        bucket = _non_dish_bucket(recipe)
        out.non_dish.append(recipe.name)
        out.non_dish_kinds[bucket] = out.non_dish_kinds.get(bucket, 0) + 1
        logger.warning(
            "富集落库: 规则判定「%s」不是一道菜(源分类=%s), 本期只观测不拦截, "
            "is_dish 保持 %s", recipe.name, recipe.cuisine, int(stored),
        )
        self._log(
            recipe, kind, "ok", provider,
            f"is_dish_guess={int(guessed)} is_dish={int(stored)} ({bucket}): 本期只观测",
        )

    def _provider_name(self) -> str:
        try:
            return self.llm.last_used or ""
        except Exception:  # noqa: BLE001
            return ""

    def _log(self, recipe: Recipe, kind: str, status: str, provider: str, message: str) -> None:
        self.session.add(RecipeEnrichLog(
            recipe_id=recipe.id,
            dish_name=recipe.name,
            kind=kind,
            status=status,
            provider=provider,
            message=message[:500] if message else None,
        ))

    # ---------------------------------------------------------------- 补新菜

    async def expand(self, limit: Optional[int] = None) -> EnrichOutcome:
        """按缺口定向补新菜

        不是"随便生成几道", 而是先看库里缺什么品类/餐次, 再让模型照着缺口写 ——
        否则补进来的全是它自己爱写的红烧肉, 决策池照样偏。
        """
        out = EnrichOutcome(kind=EnrichKind.EXPAND)
        gaps = await self.count_gaps()
        if not self.usable:
            out.degraded = True
            out.errors.append("dish_enrich 未启用或 LLM 链为空")
            return out

        want = limit or self.cfg.expand_limit
        hint = _gap_hint(gaps)
        try:
            raw = await self.llm.chat(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _expand_prompt(want, hint,
                                                               self.cfg.expand_categories)},
                ],
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
            payload = _parse_json(raw)
        except Exception as exc:  # noqa: BLE001
            out.errors.append(str(exc)[:200])
            self.last_error = str(exc)
            return out

        dishes = payload.get("dishes")
        if not isinstance(dishes, list):
            out.errors.append("返回里没有 dishes 数组")
            return out

        existing = {
            name for (name,) in (await self.session.execute(select(Recipe.name))).all()
        }
        for item in dishes[:want]:
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("name"), 20)
            if not name or name in existing:
                out.skipped += 1
                continue
            created = self._create_recipe(item, name)
            if created is None:
                out.failed += 1
                continue
            self.session.add(created)
            existing.add(name)
            out.written += 1
            out.dishes.append(name)
            self.session.add(RecipeEnrichLog(
                recipe_id=None, dish_name=name, kind=EnrichKind.EXPAND,
                status="ok", provider=self._provider_name(), fields="new_recipe",
            ))
            # 新菜默认 is_dish=1 —— 模型要是写出一道「柠檬蜂蜜水」, 这是唯一能
            # 提前看见它的地方, 所以它必须在落库这条路上
            self._observe_is_dish(created, EnrichKind.EXPAND, out, self._provider_name())
        return out

    def _create_recipe(self, item: Dict[str, Any], name: str) -> Optional[Recipe]:
        """新菜入库。字段同样要过 sanitize, 一步都不能省"""
        fields = sanitize(item)
        steps = clean_steps(item)
        if not fields.get("cook_minutes"):
            fields["cook_minutes"] = DEFAULT_MINUTES
        recipe = Recipe(
            name=name,
            source="ai_generated",
            enrich_status=EnrichStatus.PENDING,
            enrich_source=EnrichSource.LLM,
            steps_source=EnrichSource.LLM if steps else None,
            **fields,
            **steps,
        )
        return recipe


# ------------------------------------------------------------------ 提示词

_SYSTEM_PROMPT = (
    "你是一个中文菜谱数据标注员, 服务于一个帮用户决定「今天吃什么」的应用。"
    "你的输出会被直接写进数据库, 因此必须严格是 JSON, 不要解释、不要 Markdown 代码块。"
    "不知道的字段就省略, 不要编造。"
)


def _user_prompt(kind: str, recipe: Recipe) -> str:
    base = (
        f"菜名: {recipe.name}\n"
        f"已知信息: 菜系={recipe.cuisine or '未知'}, 品类={recipe.category or '未知'}, "
        f"主料={recipe.main_ingredient or '未知'}, 辣度={recipe.spice_level}\n"
    )
    if kind == EnrichKind.STEPS:
        return base + (
            "请输出 JSON: {\"quick_steps\": [3-5 步, 每步不超过 20 字], "
            "\"steps\": [详细做法 4-8 步, 每步一句话]}"
        )
    return base + (
        "请输出 JSON, 只填你有把握的字段: "
        "cook_minutes(5-240), difficulty(1-5), meal_slots(数组, 取值 "
        "breakfast/lunch/dinner/late_night), meat_type(none/egg_dairy/poultry/"
        "red_meat/seafood/mixed), tools(数组, 取值 wok/steamer/oven/air_fryer/"
        "microwave/rice_cooker/pot/pan/grill/none), season(数组, 取值 "
        "spring/summer/autumn/winter), tags(数组, 如 快手/下饭/汤羹/轻食), "
        "flavor_tags(数组, 如 辣/酸/甜/咸鲜/酱香), cover_text(不超过 4 字的角标)"
    )


def _gap_hint(gaps: Dict[str, int]) -> str:
    return (
        f"当前库里共 {gaps.get('total', 0)} 道菜, 其中缺烹饪时间 {gaps.get('cook_minutes', 0)} 道, "
        f"缺适合餐次 {gaps.get('meal_slots', 0)} 道, 缺荤型 {gaps.get('meat_type', 0)} 道, "
        f"缺做法 {gaps.get('quick_steps', 0)} 道。"
    )


def _expand_prompt(want: int, hint: str, categories: Sequence[str]) -> str:
    scope = f"只在这些品类里出: {'、'.join(categories)}。" if categories else ""
    return (
        f"{hint}\n请生成 {want} 道**库里没有**的家常菜, {scope}"
        "要求: 常见、食材在普通超市买得到、步骤不超过 6 步。\n"
        "输出 JSON: {\"dishes\": [{\"name\": 菜名, \"cuisine\": 菜系, \"category\": 品类, "
        "\"main_ingredient\": 主料, \"cook_minutes\": 分钟, \"difficulty\": 1-5, "
        "\"spice_level\": 0-4, \"is_light\": true/false, \"meal_slots\": [餐次], "
        "\"meat_type\": 荤型, \"tools\": [厨具], \"season\": [时令], "
        "\"tags\": [标签], \"flavor_tags\": [味型], \"cover_text\": 角标, "
        "\"ingredients\": [食材名], \"quick_steps\": [3-5 步], \"steps\": [4-8 步]}]}"
    )


def _parse_json(raw: str) -> Dict[str, Any]:
    """从模型的回复里抠出 JSON

    chat_with_json 已经处理了代码块, 但富集场景里模型偶尔会先说两句再给 JSON,
    所以这里再做一次"取第一个 { 到最后一个 }"的兜底。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.split("\n") if not line.startswith("```")
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start: end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"模型返回的不是 JSON: {text[:200]}") from None
