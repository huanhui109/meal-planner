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
from app.services.generation_service import (
    GenerationError,
    MenuGenerationPipeline,
    count_today_tasks,
    render_prompt,
)
from app.services.menu_service import MEAL_LABELS, MenuService
from app.services.preference_service import PreferenceService
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

# 打分权重: 热量贴合 50 + 库存命中 30 + 偏好菜系 20
SCORE_CALORIE = 50.0
SCORE_INVENTORY = 30.0
SCORE_CUISINE = 20.0
# 最多扫这么多菜谱参与打分, 避免菜谱库变大后一次拉全表
LOCAL_SCAN_LIMIT = 500
# 分数接近的候选里随机取一道, 避免每次都推同一道
LOCAL_TOP_K = 3
LOCAL_RANDOM_BAND = 5.0
AI_MAX_ATTEMPTS = 2
DEFAULT_WEEKDAY_COOK_MINUTES = 30
DEFAULT_WEEKEND_COOK_MINUTES = 60


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
        return await self._auto(menu, item, user_id, force_ai=bool(request.force_ai))

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

    async def _auto(self, menu: Menu, item: MenuItem, user_id: int, force_ai: bool = False) -> ReplacementResult:
        ctx = await self._build_context(menu, item, user_id)
        if not force_ai:
            local = await self._pick_local(ctx)
            if local is not None:
                self._apply(item, local)
                await self.db.flush()
                return ReplacementResult("local", local, menu, item)
        else:
            logger.info("用户要求直接让 AI 换一道, 跳过本地菜谱库")

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

        used = [row.recipe.name for row in menu.menu_items if row.recipe and row.recipe.name]
        exclude_names = list(dict.fromkeys(used + list(gen_ctx.history_names)))

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
        """按当前菜单设定打分挑一道; 没有合格候选返回 None -> 交给 AI"""
        stmt = (
            select(Recipe)
            .options(selectinload(Recipe.recipe_ingredients))
            .where(
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

        excluded_names = set(ctx.exclude_names)
        inventory = set(ctx.inventory_names)
        scored: List[Tuple[float, Recipe]] = []
        for recipe in recipes:
            if (recipe.name or "").strip() in excluded_names:
                continue
            if (recipe.cook_minutes or 0) > ctx.cook_minutes_cap:
                continue
            haystacks = recipe_haystacks(recipe)
            if keyword_hits(haystacks, ctx.allergens) or keyword_hits(haystacks, ctx.avoid):
                continue
            scored.append((self._score(recipe, ctx, inventory), recipe))

        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:LOCAL_TOP_K]
        best = top[0][0]
        candidates = [recipe for score, recipe in top if score >= best - LOCAL_RANDOM_BAND]
        return random.choice(candidates or [top[0][1]])

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
        return score

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
        item.recipe_id = recipe.id
        item.recipe = recipe


__all__ = [
    "ReplacementResult",
    "ReplacementQuotaExceeded",
    "ReplacementService",
    "ReplaceContext",
    "load_dish_prompt",
]
