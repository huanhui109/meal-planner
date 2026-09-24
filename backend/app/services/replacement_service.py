"""换一道 - 本地菜谱库优先, AI 降级

点一次「换一道」等于三选一:
  * ``recipe_id``  -> 直接切回已有菜谱 (「换回上一道」撤销, 不调 AI, 不占配额)
  * ``recipe_name`` -> 手动指定菜名 (旧行为, 向后兼容)
  * 留空           -> 自动: 先从本地 recipe 表按当前菜单设定挑一道;
                      挑不到才同步调 AI 生成一道, 并把结果落库供以后复用。

只有 AI 这条路径会写一条 ``is_regeneration=True`` 的生成任务, 因此它和
「重新生成整周菜单」共用同一档额度, 本地命中完全不计数。
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.fallback_chain import build_fallback_chain
from app.models.fridge_inventory import FridgeInventory
from app.models.ingredient import Ingredient
from app.models.menu import GenerationStatus, Menu, MenuGenerationTask, MenuItem
from app.models.recipe import Recipe
from app.schemas.recipe import DishGenerate, MenuItemReplaceRequest
from app.schemas.serializers import json_list
from app.services.dish_rules import dish_only
from app.services.generation_service import (
    GenerationError,
    MenuGenerationPipeline,
    count_today_tasks,
    render_prompt,
)
from app.services.menu_service import MEAL_LABELS, MenuService
from app.services.preference_service import PreferenceService
from app.services.pricing_service import PricedRow, PricingService
from app.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

DISH_PROMPT_FILENAME = "dish_replacement.txt"
"""单菜提示词里的固定说法, DemoLLMClient 靠它区分「整周」与「单道菜」请求"""
DISH_PROMPT_MARKER = "只生成一道菜"

FALLBACK_DISH_PROMPT = (
    "你是专业营养师兼家庭厨师。只生成一道菜, 用来替换周菜单里的一餐。\n"
    "用户信息:\n{user_info}\n\n冰箱库存:\n{inventory}\n\n约束:\n{constraints}\n\n"
    "烹饪时间不超过 {cook_minutes} 分钟。\n只输出 JSON: "
    '{"name": "", "ingredients": [{"name": "", "quantity": 1, "unit": ""}], '
    '"calories": 0, "protein_g": 0, "carb_g": 0, "fat_g": 0, "cook_minutes": 20, "steps": ""}'
)

# 打分权重: 热量贴合 50 + 库存命中 30 + 偏好菜系 20 (原有三项口径)
SCORE_CALORIE = 50.0
SCORE_INVENTORY = 30.0
# 暂停(不是废弃), 与 config.py 的 DecideSettings.score_cuisine 同源: recipe.cuisine 列
# 现在装的是菜品分类(荤菜/主食/早餐…), 不是菜系, 和用户的 cuisines (川湘/粤菜/江浙…)
# 对不上, 396 道里只命中 2 道, 20 分只是假装在打分。
# 恢复条件: recipe.cuisine 由凌晨 LLM 富集任务标注成真菜系并回填完成, 且 config.py 的
# 恢复清单(6 处 + test_decide_parity.py 的断言)一起改 —— 本处是模块级硬编码, 不受
# DecideSettings 管, 最容易在那天被漏掉。恢复目标 20.0(原值)。
# 恢复前先确认幅度不超过 LOCAL_RANDOM_BAND: 这里是"先截 top3 再切带", 比决策链路更陡,
# 20 分直接生效会让「换一换」塌缩成只在命中菜系的菜里换。
SCORE_CUISINE = 0.0
# 个性化口味: 辣度贴合 + 味型/场景标签命中 (口径与 decision_service 对齐)
SCORE_SPICE = 12.0
SCORE_TASTE = 12.0
# 预算: 落在每餐预算内给满分, 略微超出给部分分, 超得一截扣分
SCORE_BUDGET = 15.0
BUDGET_OVER_TOLERANCE = 1.2
# 最多扫这么多菜谱参与打分, 避免菜谱库变大后一次拉全表
LOCAL_SCAN_LIMIT = 500
# 分数接近的候选里随机取一道, 避免每次都推同一道
LOCAL_TOP_K = 3
LOCAL_RANDOM_BAND = 5.0
AI_MAX_ATTEMPTS = 2
DEFAULT_WEEKDAY_COOK_MINUTES = 30
DEFAULT_WEEKEND_COOK_MINUTES = 60
# 单餐「已经换掉过」的记录上限, 超出丢掉最老的
MAX_REJECTED_RECIPES = 30


class ReplacementQuotaExceeded(Exception):
    """AI 降级超出当日重新生成额度"""


@dataclass
class ReplacementResult:
    """换一道的结果: 走哪条路径 + 换成了哪道菜 + 换完后的菜单"""

    source: str  # local / ai / restore / manual
    recipe: Recipe
    menu: Menu
    item: MenuItem


@dataclass
class ReplaceContext:
    """挑菜/生成前拍平的只读上下文 (不含 ORM 对象, 可安全跨事务使用)"""

    user_id: int
    menu_id: int
    item_id: int
    meal_date: date
    meal_type: str
    week_start: date
    cook_minutes_cap: int
    target_calories: Optional[float]
    exclude_names: List[str]
    allergens: List[str]
    avoid: List[str]
    cuisines: List[str]
    pref_context: str
    inventory_lines: List[str]
    inventory_names: List[str]
    # 本餐已经被「换一道」换掉过的菜谱 id, 打分时必须排除, 否则会在两道菜之间来回跳
    rejected_ids: List[int]
    # 用户辣度 0-5 (菜谱是 0-4, 与 decision_service 一样按 4.0 归一)
    spice_level: int
    # 用户的口味偏好 + 场景标签, 与菜谱的 tags / flavor_tags 匹配
    taste_tags: List[str]
    # 这一餐的预算上限: 日预算按餐次均摊
    meal_budget: Optional[float]


def load_dish_prompt() -> str:
    path = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / DISH_PROMPT_FILENAME
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("未找到 prompt 模板 %s, 使用内置提示词", path)
        return FALLBACK_DISH_PROMPT


def recipe_haystacks(recipe: Recipe) -> List[str]:
    """菜名 + 食材名, 用于过敏源/忌口的包含判定"""
    names = [recipe.name or ""]
    for row in recipe.recipe_ingredients or []:
        if row.ingredient is not None:
            names.append(row.ingredient.name or "")
    return names


def keyword_hits(texts: Sequence[str], keywords: Sequence[str]) -> List[str]:
    if not keywords:
        return []
    return [word for word in keywords if any(word in text for text in texts)]


class ReplacementService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Optional[Settings] = None,
        llm: Optional[LLMClient] = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self._llm = llm

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = build_fallback_chain(self.settings)
        return self._llm

    # ---------- 入口 ----------

    async def replace(
        self,
        menu: Menu,
        item: MenuItem,
        user_id: int,
        request: Optional[MenuItemReplaceRequest] = None,
    ) -> ReplacementResult:
        request = request or MenuItemReplaceRequest()
        if request.recipe_id is not None:
            return await self._restore(menu, item, request.recipe_id)
        if (request.recipe_name or "").strip():
            return await self._manual(menu, item, request)
        return await self._auto(menu, item, user_id)

    # ---------- 三条路径 ----------

    async def _restore(self, menu: Menu, item: MenuItem, recipe_id: int) -> ReplacementResult:
        """换回上一道: 直接切到已有菜谱, 不调 AI 也不占配额"""
        recipe = await self.db.get(Recipe, recipe_id)
        if recipe is None:
            raise GenerationError("想换回的那道菜已经不在菜谱库里了")
        self._apply(item, recipe)
        await self.db.flush()
        return ReplacementResult("restore", recipe, menu, item)

    async def _manual(
        self, menu: Menu, item: MenuItem, request: MenuItemReplaceRequest
    ) -> ReplacementResult:
        """旧的手动指定菜名路径, 保留向后兼容"""
        replaced = await MenuService(self.db).replace_item(menu, item, request)
        return ReplacementResult("manual", replaced.recipe, menu, item)

    async def _auto(self, menu: Menu, item: MenuItem, user_id: int) -> ReplacementResult:
        ctx = await self._build_context(menu, item, user_id)
        local = await self._pick_local(ctx)
        if local is not None:
            self._apply(item, local)
            await self.db.flush()
            return ReplacementResult("local", local, menu, item)

        # AI 可能耗时几十秒, 先结束当前事务把连接还回连接池, 不能占着连接等模型
        menu_id, item_id = menu.id, item.id
        await self.db.rollback()
        recipe = await self._generate_with_ai(ctx)

        menu = await MenuService(self.db).get_menu(menu_id, user_id)
        if menu is None:
            raise GenerationError("菜单已不存在, 请刷新后重试")
        item = next((row for row in menu.menu_items if row.id == item_id), None)
        if item is None:
            raise GenerationError("这一餐已经被改掉了, 请刷新后重试")
        self._apply(item, recipe)
        await self.db.flush()
        return ReplacementResult("ai", recipe, menu, item)

    # ---------- 上下文 ----------

    async def _build_context(self, menu: Menu, item: MenuItem, user_id: int) -> ReplaceContext:
        pipeline = MenuGenerationPipeline(self._get_llm(), self.settings)
        gen_ctx = await pipeline.prepare(user_id, menu.week_start_date)

        prefs = PreferenceService(self.db)
        household = await prefs.get_household(user_id)
        diet = await prefs.get_diet_preference(user_id)

        is_weekend = item.meal_date.weekday() >= 5
        if household:
            cook_cap = household.weekend_cook_minutes if is_weekend else household.weekday_cook_minutes
            meals_per_day = household.meals_per_day or 2
        else:
            cook_cap = DEFAULT_WEEKEND_COOK_MINUTES if is_weekend else DEFAULT_WEEKDAY_COOK_MINUTES
            meals_per_day = 2

        target = None
        if gen_ctx.target_calories:
            target = float(gen_ctx.target_calories) / meals_per_day

        # 每餐预算: 日预算按当日餐次均摊; 用户没设过预算就不参与打分
        budget = await prefs.get_budget(user_id)
        meal_budget: Optional[float] = None
        if budget:
            daily = budget.weekend_daily_budget if is_weekend else budget.weekday_daily_budget
            if daily and daily > 0:
                meal_budget = float(daily) / meals_per_day

        # 本餐已经换掉过的菜。
        # 光靠「当前菜单里有哪些菜」是记不住的: A 换成 B 之后 A 就从菜单里消失了,
        # 下一次打分它又是高分候选 —— 这就是「换一道」在两道菜之间来回跳的根因。
        rejected_ids = self._load_rejected_ids(item.rejected_recipe_ids)
        rejected_names: List[str] = []
        if rejected_ids:
            rows = (
                await self.db.execute(select(Recipe.name).where(Recipe.id.in_(rejected_ids)))
            ).scalars().all()
            rejected_names = [str(name) for name in rows if name]

        used = [row.recipe.name for row in menu.menu_items if row.recipe and row.recipe.name]
        exclude_names = list(dict.fromkeys(used + rejected_names + list(gen_ctx.history_names)))

        taste_tags = self._split_pref(diet.flavor_preference if diet else None) + json_list(
            diet.scene_tags if diet else None
        )

        return ReplaceContext(
            user_id=user_id,
            menu_id=menu.id,
            item_id=item.id,
            meal_date=item.meal_date,
            meal_type=item.meal_type,
            week_start=menu.week_start_date,
            cook_minutes_cap=max(1, int(cook_cap or DEFAULT_WEEKDAY_COOK_MINUTES)),
            target_calories=target,
            exclude_names=exclude_names,
            allergens=list(gen_ctx.allergens),
            avoid=list(gen_ctx.avoid_ingredients),
            cuisines=json_list(diet.cuisines) if diet else [],
            pref_context=gen_ctx.pref_context,
            inventory_lines=list(gen_ctx.inventory_lines),
            inventory_names=await self._inventory_names(user_id),
            rejected_ids=rejected_ids,
            spice_level=int(diet.spice_level) if diet and diet.spice_level is not None else 2,
            taste_tags=list(dict.fromkeys(taste_tags)),
            meal_budget=meal_budget,
        )

    async def _inventory_names(self, user_id: int) -> List[str]:
        result = await self.db.execute(
            select(Ingredient.name)
            .join(FridgeInventory, FridgeInventory.ingredient_id == Ingredient.id)
            .where(FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0)
        )
        return [row[0] for row in result.all() if row[0]]

    # ---------- 本地库 ----------

    async def _pick_local(self, ctx: ReplaceContext) -> Optional[Recipe]:
        """按当前菜单设定打分挑一道; 没有合格候选返回 None -> 交给 AI

        dish_only() 这道闸和决策主链路是同一个 —— 「换一个」是二级决策入口,
        少了它用户就能在这儿刷出油泼辣子。
        """
        stmt = (
            select(Recipe)
            .options(selectinload(Recipe.recipe_ingredients))
            .where(
                dish_only(),
                Recipe.calories.is_not(None),
                Recipe.cook_minutes.is_not(None),
                Recipe.steps.is_not(None),
                Recipe.steps != "",
                Recipe.recipe_ingredients.any(),
            )
            .order_by(Recipe.id.desc())
            .limit(LOCAL_SCAN_LIMIT)
        )
        recipes = list((await self.db.execute(stmt)).scalars().all())

        inventory = set(ctx.inventory_names)
        scored = self._collect(recipes, ctx, inventory, skip_rejected=False)
        if not scored:
            # 这一餐换过的菜把候选滤光了: 放宽去重, 只保证不与当前菜单/历史重名,
            # 也好过直接掉进 AI 降级把配额吃掉
            scored = self._collect(recipes, ctx, inventory, skip_rejected=True)
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:LOCAL_TOP_K]
        best = top[0][0]
        candidates = [recipe for score, recipe in top if score >= best - LOCAL_RANDOM_BAND]
        return random.choice(candidates or [top[0][1]])

    def _collect(
        self,
        recipes: Sequence[Recipe],
        ctx: ReplaceContext,
        inventory: set,
        skip_rejected: bool,
    ) -> List[Tuple[float, Recipe]]:
        """过滤 + 打分; skip_rejected=True 时不再管「换过」名单"""
        rejected: set = set() if skip_rejected else set(ctx.rejected_ids)
        excluded_names = set(ctx.exclude_names)
        scored: List[Tuple[float, Recipe]] = []
        for recipe in recipes:
            # 这一餐之前被换掉过的菜不再端上来, 否则会和当前这道来回横跳
            if recipe.id in rejected:
                continue
            if (recipe.name or "").strip() in excluded_names:
                continue
            if (recipe.cook_minutes or 0) > ctx.cook_minutes_cap:
                continue
            haystacks = recipe_haystacks(recipe)
            if keyword_hits(haystacks, ctx.allergens) or keyword_hits(haystacks, ctx.avoid):
                continue
            scored.append((self._score(recipe, ctx, inventory), recipe))
        return scored

    def _score(self, recipe: Recipe, ctx: ReplaceContext, inventory: set) -> float:
        score = 0.0
        if ctx.target_calories:
            deviation = abs((recipe.calories or 0) - ctx.target_calories) / ctx.target_calories
            score += SCORE_CALORIE * max(0.0, 1.0 - min(1.0, deviation))
        else:
            score += SCORE_CALORIE * 0.5

        names = [
            row.ingredient.name
            for row in recipe.recipe_ingredients or []
            if row.ingredient is not None and row.ingredient.name
        ]
        if names:
            hits = sum(1 for name in names if name in inventory)
            score += SCORE_INVENTORY * hits / len(names)

        if ctx.cuisines and recipe.cuisine and recipe.cuisine in ctx.cuisines:
            score += SCORE_CUISINE

        # 辣度贴合 (用户 0-5 / 菜谱 0-4, 与 decision_service 同一口径)
        gap = abs((recipe.spice_level or 0) - ctx.spice_level) / 4.0
        score += SCORE_SPICE * max(0.0, 1.0 - min(1.0, gap))

        # 味型 / 场景标签: 与用户口味偏好对得上的加分
        if ctx.taste_tags:
            dish_tags = set(json_list(recipe.tags) + json_list(recipe.flavor_tags))
            hits = sum(1 for tag in ctx.taste_tags if tag in dish_tags)
            if hits:
                score += SCORE_TASTE * min(1.0, hits / len(ctx.taste_tags))

        # 预算: 只有估得出价的菜才参与这一项, 估不出价的不奖不罚
        cost = self._recipe_cost(recipe)
        if ctx.meal_budget and cost is not None:
            if cost <= ctx.meal_budget:
                score += SCORE_BUDGET
            elif cost <= ctx.meal_budget * BUDGET_OVER_TOLERANCE:
                score += SCORE_BUDGET * 0.4
            else:
                score -= SCORE_BUDGET
        return score

    def _recipe_cost(self, recipe: Recipe) -> Optional[float]:
        """按食材参考单价估一道菜的成本; 一个价都查不到返回 None"""
        rows = []
        for row in recipe.recipe_ingredients or []:
            ingredient = row.ingredient
            if ingredient is None:
                continue
            rows.append(
                PricedRow(
                    ingredient_name=ingredient.name or "",
                    quantity=row.quantity,
                    unit=row.unit or "",
                    reference_price=ingredient.reference_price,
                    standard_unit=ingredient.standard_unit or "",
                )
            )
        if not rows:
            return None
        estimate = PricingService().estimate(rows)
        if estimate.priced_items == 0:
            return None
        return estimate.total

    # ---------- AI 降级 ----------

    async def _generate_with_ai(self, ctx: ReplaceContext) -> Recipe:
        used = await count_today_tasks(self.db, ctx.user_id, is_regeneration=True)
        if used >= self.settings.menu.daily_regenerate_limit:
            raise ReplacementQuotaExceeded(
                f"今日「换一道」的 AI 生成次数已用尽 (上限 {self.settings.menu.daily_regenerate_limit} 次), 明天再试"
            )

        llm = self._get_llm()
        messages = self._build_dish_messages(ctx)
        exclude_names = set(ctx.exclude_names)
        last_error: Optional[Exception] = None

        for _ in range(AI_MAX_ATTEMPTS):
            try:
                payload = await llm.chat_with_json(
                    messages=messages,
                    temperature=0.9,
                    max_tokens=self.settings.llm.primary.max_tokens,
                )
                dish = DishGenerate(**payload)
            except Exception as exc:  # noqa: BLE001 - LLM 输出不可信, 统一转成可读错误
                last_error = exc
                logger.warning("AI 换一道失败, 重试: %s", exc)
                continue

            name = (dish.name or "").strip()
            hits = keyword_hits([name] + [ing.name for ing in dish.ingredients], ctx.allergens)
            if name and name not in exclude_names and not hits:
                return await self._persist_dish(dish, ctx)

            reason = "含过敏源" if hits else "与已有菜重复"
            logger.info("AI 换一道结果不合格(%s): %s", reason, name or "(空)")
            last_error = GenerationError(f"AI 给出的菜{reason}, 请重试")
            messages = messages + [
                {
                    "role": "user",
                    "content": "上一道不合格, 请换一道完全不同的菜, 避开: "
                    + ", ".join(sorted(exclude_names)[:20]),
                }
            ]
            exclude_names.add(name)

        raise GenerationError(f"AI 换一道失败: {last_error}") from last_error

    def _build_dish_messages(self, ctx: ReplaceContext) -> List[dict]:
        constraints = []
        if ctx.allergens:
            constraints.append(f"过敏源绝对不能出现 (含别名与配料): {', '.join(ctx.allergens)}")
        if ctx.avoid:
            constraints.append(f"忌口食材尽量避免: {', '.join(ctx.avoid)}")
        if ctx.exclude_names:
            constraints.append(f"不要与这些菜重名: {', '.join(ctx.exclude_names[:30])}")
        if ctx.target_calories:
            constraints.append(f"这一餐的目标热量约 {ctx.target_calories:.0f} kcal")
        constraints.append(f"烹饪时间不超过 {ctx.cook_minutes_cap} 分钟")

        meal_context = (
            f"{ctx.meal_date} ({'周末' if ctx.meal_date.weekday() >= 5 else '工作日'}) 的"
            f"{MEAL_LABELS.get(ctx.meal_type, ctx.meal_type)}"
        )
        prompt = render_prompt(
            load_dish_prompt(),
            user_info=ctx.pref_context,
            inventory="\n".join(ctx.inventory_lines) or "暂无库存数据",
            constraints="\n".join(constraints) or "无特殊约束",
            meal_context=meal_context,
            cook_minutes=str(ctx.cook_minutes_cap),
        )
        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"请为{meal_context}换一道菜, {DISH_PROMPT_MARKER}, 只输出 JSON。",
            },
        ]

    async def _persist_dish(self, dish: DishGenerate, ctx: ReplaceContext) -> Recipe:
        recipe = await RecipeService(self.db).find_or_create_recipe(
            name=dish.name,
            cook_minutes=dish.cook_minutes,
            calories=dish.calories,
            protein_g=dish.protein_g,
            carb_g=dish.carb_g,
            fat_g=dish.fat_g,
            steps=dish.steps,
            ingredients=dish.ingredients,
        )
        # 记一条重生成任务, 让这次 AI 消耗计入重新生成额度
        self.db.add(
            MenuGenerationTask(
                user_id=ctx.user_id,
                status=GenerationStatus.SUCCEEDED,
                menu_id=ctx.menu_id,
                week_start_date=ctx.week_start,
                request_payload=json.dumps(
                    {"action": "replace_item", "item_id": ctx.item_id}, ensure_ascii=False
                ),
                is_regeneration=True,
                attempts=1,
                finished_at=datetime.now(),
            )
        )
        await self.db.flush()
        return recipe

    # ---------- 落库 ----------

    def _apply(self, item: MenuItem, recipe: Recipe) -> None:
        # 被换掉的那道菜记进本餐的名单, 之后的「换一道」不会再把它端回来
        previous_id = item.recipe_id
        if previous_id and previous_id != recipe.id:
            item.rejected_recipe_ids = self._append_rejected(item.rejected_recipe_ids, previous_id)
        item.recipe_id = recipe.id
        item.recipe = recipe

    # ---------- 「已换过」名单 ----------

    def _load_rejected_ids(self, raw: Optional[str]) -> List[int]:
        """解析 menu_item.rejected_recipe_ids; 数据脏了按空处理, 不让历史包袱挡住换菜"""
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("rejected_recipe_ids 不是合法 JSON, 按空处理: %r", raw)
            return []
        if not isinstance(payload, list):
            return []
        ids: List[int] = []
        for value in payload:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return ids

    def _append_rejected(self, raw: Optional[str], recipe_id: int) -> str:
        ids = self._load_rejected_ids(raw)
        if recipe_id not in ids:
            ids.append(recipe_id)
        return json.dumps(ids[-MAX_REJECTED_RECIPES:])

    @staticmethod
    def _split_pref(raw: Optional[str]) -> List[str]:
        """口味偏好可能是 JSON 数组, 也可能是「微辣, 清淡」这种手填文本"""
        if not raw:
            return []
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if str(item).strip()]
        for separator in (",", "，", "、", "/", "|"):
            text = text.replace(separator, ",")
        return [part.strip() for part in text.split(",") if part.strip()]


__all__ = [
    "ReplacementResult",
    "ReplacementQuotaExceeded",
    "ReplacementService",
    "ReplaceContext",
    "load_dish_prompt",
]
