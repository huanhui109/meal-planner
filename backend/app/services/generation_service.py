"""F2 菜单生成 - 后台任务队列与 LLM 生成流水线

设计要点:
  * 接口只入队, 由进程内 worker 用 SELECT ... FOR UPDATE SKIP LOCKED 领取任务。
  * LLM 调用阶段不持有数据库连接 (长耗时不能占用连接池)。
  * 单次生成只调用一次 LLM; 多样性不达标时最多再生成一次并取更优结果。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.database import async_session_factory, session_scope
from app.llm.base import LLMClient
from app.llm.fallback_chain import build_fallback_chain
from app.models.allergy_restriction import AllergyRestriction
from app.models.budget import Budget
from app.models.fridge_inventory import FridgeInventory
from app.models.health_goal import HealthGoal
from app.models.ingredient import Ingredient
from app.models.menu import GenerationStatus, Menu, MenuGenerationTask, MenuItem, MenuStatus
from app.models.recipe import Recipe, RecipeIngredient
from app.schemas.recipe import (
    DayGenerateItem,
    IngredientItem,
    MealGenerateItem,
    RecipeGenerateItem,
    WeekMenuGenerate,
)
from app.services.budget_service import BudgetService
from app.services.diversity_service import DiversityReport, DiversityService
from app.services.menu_service import MenuService
from app.services.nutrition_service import NutritionReport
from app.services.preference_service import PreferenceService
from app.services.pricing_service import CostEstimate
from app.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

PROMPT_FILENAME = "menu_generation.txt"
DEFAULT_SYSTEM_PROMPT = "你是专业营养师, 根据用户偏好生成一周菜单. 严格按 JSON 格式输出."
VALID_MEAL_TYPES = ("breakfast", "lunch", "dinner")
ERROR_MESSAGE_LIMIT = 500
MAX_MENU_DAYS = 7

# 生成模式: auto 本地优先+AI兜底 / local 只用本地 / ai 只用模型
MODE_AUTO = "auto"
MODE_LOCAL = "local"
MODE_AI = "ai"

# 本地编排打分权重 (与 replacement_service 口径一致)
SCORE_CALORIE = 50.0
SCORE_INVENTORY = 30.0
SCORE_CUISINE = 20.0
DEFAULT_WEEKDAY_COOK_MINUTES = 30
DEFAULT_WEEKEND_COOK_MINUTES = 60
# 给 LLM 的本地候选短名单长度 (mixed 模式)
LOCAL_HINT_LIMIT = 30


class GenerationError(Exception):
    """生成流程的可读错误"""


@dataclass
class GenerationContext:
    """LLM 调用前需要的数据 (只读, 不含 ORM 对象)"""

    user_id: int
    week_start: date
    pref_context: str
    inventory_lines: List[str]
    history_names: List[str]
    allergens: List[str] = field(default_factory=list)
    avoid_ingredients: List[str] = field(default_factory=list)
    cuisines: List[str] = field(default_factory=list)
    target_calories: Optional[float] = None
    weekly_cap: Optional[float] = None
    weekday_budget: Optional[float] = None
    weekend_budget: Optional[float] = None
    # 本地编排用: 每日餐次与工作日/周末烹饪时长上限
    meals_per_day: int = 2
    weekday_cook_minutes: int = DEFAULT_WEEKDAY_COOK_MINUTES
    weekend_cook_minutes: int = DEFAULT_WEEKEND_COOK_MINUTES


@dataclass
class LocalPlan:
    """本地编排结果: 拼成功的周菜单 (可能为 None) 与给 LLM 的候选短名单"""

    week: Optional[WeekMenuGenerate] = None
    hints: List[str] = field(default_factory=list)


@dataclass
class GenerationOutcome:
    menu_id: int
    week_start: date
    diversity: DiversityReport
    nutrition: NutritionReport
    cost: CostEstimate
    warnings: List[str] = field(default_factory=list)


def render_prompt(template: str, **values: str) -> str:
    """占位符替换 (不能用 str.format, 模板内有 JSON 花括号)"""
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value or "")
    return text


def _json_list(raw: Optional[str]) -> List[str]:
    """JSON 数组字段的容错解析"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def _payload_mode(payload: Optional[str]) -> str:
    """从任务 request_payload 里取生成模式, 缺失或非法时按 auto 处理"""
    try:
        data = json.loads(payload or "{}")
    except (json.JSONDecodeError, TypeError):
        return MODE_AUTO
    mode = str(data.get("mode") or MODE_AUTO).lower()
    return mode if mode in (MODE_AUTO, MODE_LOCAL, MODE_AI) else MODE_AUTO


def find_allergen_hits(recipe_data, allergens: Sequence[str]) -> List[str]:
    """命中过敏源的菜谱: 菜名或任一食材名包含过敏源关键词"""
    if not allergens:
        return []
    haystacks = [recipe_data.name or ""] + [item.name or "" for item in (recipe_data.ingredients or [])]
    return [allergen for allergen in allergens if any(allergen in text for text in haystacks)]


def load_system_prompt() -> str:
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / PROMPT_FILENAME
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("未找到 prompt 模板 %s, 使用内置提示词", path)
        return DEFAULT_SYSTEM_PROMPT


async def create_generation_task(
    db: AsyncSession,
    user_id: int,
    week_start: date,
    payload: Optional[dict] = None,
    is_regeneration: bool = False,
) -> MenuGenerationTask:
    """写入一条待处理任务

    is_regeneration 决定这条任务算在哪个配额里: 重新生成走更宽松的独立额度,
    不会被"今日生成次数已用尽"挡住。
    """
    task = MenuGenerationTask(
        user_id=user_id,
        week_start_date=week_start,
        status=GenerationStatus.PENDING,
        request_payload=json.dumps(payload or {}, ensure_ascii=False),
        is_regeneration=is_regeneration,
    )
    db.add(task)
    await db.flush()
    return task


async def count_today_tasks(
    db: AsyncSession,
    user_id: int,
    is_regeneration: bool = False,
) -> int:
    """当日已创建的生成任务数 (含失败), 用于配额判断

    按 is_regeneration 分开计数: 首次生成与重新生成各自有独立额度,
    否则用户把菜单改两下就会被"今日生成次数已用尽"挡住。
    """
    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    result = await db.execute(
        select(func.count(MenuGenerationTask.id)).where(
            MenuGenerationTask.user_id == user_id,
            MenuGenerationTask.created_at >= start,
            MenuGenerationTask.is_regeneration.is_(is_regeneration),
        )
    )
    return int(result.scalar() or 0)


async def load_profile_snapshot(user_id: int) -> Dict[str, object]:
    """一次性取回用户的健康目标与预算 (用于生成后校验)"""
    async with session_scope() as session:
        goal = (
            await session.execute(select(HealthGoal).where(HealthGoal.user_id == user_id))
        ).scalar_one_or_none()
        budget = (await session.execute(select(Budget).where(Budget.user_id == user_id))).scalar_one_or_none()
        return {
            "target_calories": goal.daily_calories if goal else None,
            "weekly_cap": budget.weekly_cap if budget else None,
            "weekday_budget": budget.weekday_daily_budget if budget else None,
            "weekend_budget": budget.weekend_daily_budget if budget else None,
        }


class MenuGenerationPipeline:
    """一次完整的生成: 准备上下文 -> 调 LLM -> 落库 -> 校验"""

    def __init__(self, llm: LLMClient, settings: Optional[Settings] = None):
        self.llm = llm
        self.settings = settings or get_settings()
        self.diversity_service = DiversityService()
        self.budget_service = BudgetService()

    # ---------- 1. 准备 ----------

    async def prepare(self, user_id: int, week_start: date) -> GenerationContext:
        async with session_scope() as session:
            pref_service = PreferenceService(session)
            pref_context = await pref_service.get_preference_prompt_context(user_id)
            menu_service = MenuService(session)
            history = await menu_service.history_recipe_names(
                user_id, week_start, self.settings.menu.history_weeks
            )
            inventory = await self._inventory_lines(session, user_id)
            allergy = (
                await session.execute(select(AllergyRestriction).where(AllergyRestriction.user_id == user_id))
            ).scalar_one_or_none()
            allergens = _json_list(allergy.allergens if allergy else None)
            avoids = _json_list(allergy.avoid_ingredients if allergy else None)
            household = await pref_service.get_household(user_id)
            diet = await pref_service.get_diet_preference(user_id)
        profile = await load_profile_snapshot(user_id)
        return GenerationContext(
            user_id=user_id,
            week_start=week_start,
            pref_context=pref_context,
            inventory_lines=inventory,
            history_names=history,
            allergens=allergens,
            avoid_ingredients=avoids,
            cuisines=_json_list(diet.cuisines) if diet else [],
            meals_per_day=household.meals_per_day if household else 2,
            weekday_cook_minutes=(
                household.weekday_cook_minutes if household else DEFAULT_WEEKDAY_COOK_MINUTES
            ),
            weekend_cook_minutes=(
                household.weekend_cook_minutes if household else DEFAULT_WEEKEND_COOK_MINUTES
            ),
            **profile,  # type: ignore[arg-type]
        )

    async def _inventory_lines(self, session: AsyncSession, user_id: int, limit: int = 30) -> List[str]:
        result = await session.execute(
            select(
                Ingredient.name, FridgeInventory.quantity, FridgeInventory.unit, FridgeInventory.expiry_date
            )
            .join(Ingredient, Ingredient.id == FridgeInventory.ingredient_id)
            .where(FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0)
            .order_by(
                FridgeInventory.expiry_date.is_(None),
                FridgeInventory.expiry_date.asc(),
            )
            .limit(limit)
        )
        lines: List[str] = []
        for name, quantity, unit, expiry in result.all():
            suffix = f", {expiry} 到期" if expiry else ""
            lines.append(f"- {name} {quantity:g}{unit}{suffix}")
        return lines

    # ---------- 2. 调 LLM ----------

    def build_messages(self, ctx: GenerationContext, hint_names: Sequence[str] = ()) -> List[Dict[str, str]]:
        allergy_block, avoid_block = self._split_constraints(ctx)
        constraints = (
            "\n".join(part for part in (allergy_block, avoid_block, self._cook_time_block(ctx)) if part)
            or "无特殊约束"
        )
        if ctx.history_names:
            constraints += f"\n近期已做过 (避免重复): {', '.join(ctx.history_names[:30])}"

        if ctx.inventory_lines:
            inventory_text = "\n".join(ctx.inventory_lines)
        else:
            inventory_text = "暂无库存数据"

        prompt = render_prompt(
            load_system_prompt(),
            user_info=ctx.pref_context,
            inventory=inventory_text,
            constraints=constraints,
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"请生成 {ctx.week_start} 至 {ctx.week_start + timedelta(days=6)} "
                    "这一周的菜单, 只输出 JSON。"
                ),
            },
        ]
        if hint_names:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "优先从这些本地菜谱库里挑选, 不足的部分再自行发挥: "
                        + ", ".join(hint_names[:LOCAL_HINT_LIMIT])
                    ),
                }
            )
        return messages

    def _split_constraints(self, ctx: GenerationContext) -> Tuple[str, str]:
        """硬约束必须回显给模型 (过敏源是安全红线)"""
        allergy_block = (
            f"过敏源绝对不能出现 (含任何别名与配料): {', '.join(ctx.allergens)}" if ctx.allergens else ""
        )
        avoid_block = f"忌口食材尽量避免: {', '.join(ctx.avoid_ingredients)}" if ctx.avoid_ingredients else ""
        return allergy_block, avoid_block

    def _cook_time_block(self, ctx: GenerationContext) -> str:
        return "工作日单菜烹饪时间不超过 30 分钟, 周末可放宽到 60 分钟"

    async def call_llm(
        self,
        ctx: GenerationContext,
        avoid_names: Sequence[str] = (),
        hint_names: Sequence[str] = (),
    ) -> Tuple[WeekMenuGenerate, List[str]]:
        messages = self.build_messages(ctx, hint_names=hint_names)
        if avoid_names:
            messages.append(
                {
                    "role": "user",
                    "content": "上一次生成与近期菜单重复, 请避免以下菜名: " + ", ".join(avoid_names[:20]),
                }
            )
        parsed = await self.llm.chat_with_json(
            messages=messages,
            temperature=0.8,
            max_tokens=self.settings.llm.primary.max_tokens,
        )
        try:
            week = WeekMenuGenerate(**parsed)
        except Exception as exc:  # noqa: BLE001 - LLM 输出不可信
            raise GenerationError(f"模型返回结构不符合预期: {exc}") from exc
        if not week.week_menu:
            raise GenerationError("模型没有返回任何菜单")
        return week, []

    # ---------- 2.5 本地菜谱库编排 ----------

    def _slot_plan(self, ctx: GenerationContext) -> List[Tuple[int, str]]:
        """7 天 × 餐次 (按家庭每日餐次取午餐/晚餐或三餐)"""
        count = max(1, min(len(VALID_MEAL_TYPES), ctx.meals_per_day or 2))
        meal_types = VALID_MEAL_TYPES[-count:]
        return [(day, meal) for day in range(MAX_MENU_DAYS) for meal in meal_types]

    async def _load_local_candidates(self, ctx: GenerationContext) -> List[Recipe]:
        async with session_scope() as session:
            stmt = (
                select(Recipe)
                .options(selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient))
                .where(
                    Recipe.calories.is_not(None),
                    Recipe.cook_minutes.is_not(None),
                    Recipe.steps.is_not(None),
                    Recipe.steps != "",
                    Recipe.recipe_ingredients.any(),
                )
                .order_by(Recipe.id.desc())
                .limit(self.settings.menu.local_candidate_pool)
            )
            return list((await session.execute(stmt)).scalars().all())

    async def _inventory_name_set(self, user_id: int) -> set:
        async with session_scope() as session:
            result = await session.execute(
                select(Ingredient.name)
                .join(FridgeInventory, FridgeInventory.ingredient_id == Ingredient.id)
                .where(FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0)
            )
            return {row[0] for row in result.all() if row[0]}

    def _pick_for_slot(
        self,
        recipes: Sequence[Recipe],
        chosen_ids: set,
        used_names: set,
        ctx: GenerationContext,
        inventory: set,
        cook_cap: int,
        target_calories: Optional[float],
    ) -> Optional[Recipe]:
        scored: List[Tuple[float, Recipe]] = []
        for recipe in recipes:
            if recipe.id in chosen_ids or (recipe.name or "") in used_names:
                continue
            if (recipe.cook_minutes or 0) > cook_cap:
                continue
            haystacks = _recipe_haystacks(recipe)
            if keyword_hits(haystacks, ctx.allergens) or keyword_hits(haystacks, ctx.avoid_ingredients):
                continue
            scored.append((_score_recipe(recipe, target_calories, inventory, ctx.cuisines), recipe))
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:3]
        best = top[0][0]
        band = [recipe for score, recipe in top if score >= best - 5.0]
        return random.choice(band or [top[0][1]])

    async def compose_from_local(self, ctx: GenerationContext) -> LocalPlan:
        """用本地菜谱库拼一周菜单

        填充率达标 -> 返回拼好的周菜单 (source=local);
        不达标 -> 返回候选短名单, 交给 LLM 兜底 (source=mixed/ai)。
        """
        slots = self._slot_plan(ctx)
        if not slots:
            return LocalPlan()
        recipes = await self._load_local_candidates(ctx)
        if not recipes:
            return LocalPlan()

        inventory = await self._inventory_name_set(ctx.user_id)
        target_calories = _per_meal_calories(ctx)
        used_names = set(ctx.history_names)
        chosen: Dict[Tuple[int, str], Recipe] = {}
        chosen_ids: set = set()

        for day_index, meal_type in slots:
            meal_date = ctx.week_start + timedelta(days=day_index)
            cook_cap = (
                ctx.weekend_cook_minutes if meal_date.weekday() >= 5 else ctx.weekday_cook_minutes
            )
            recipe = self._pick_for_slot(
                recipes, chosen_ids, used_names, ctx, inventory, cook_cap, target_calories
            )
            if recipe is None:
                continue
            chosen[(day_index, meal_type)] = recipe
            chosen_ids.add(recipe.id)
            used_names.add(recipe.name)

        if len(chosen) / len(slots) >= self.settings.menu.local_min_fill:
            logger.info("本地菜谱库拼齐一周: %s/%s 餐次", len(chosen), len(slots))
            return LocalPlan(week=_build_week(ctx, chosen))
        hints = [r.name for r in recipes if (r.name or "") not in ctx.history_names][:LOCAL_HINT_LIMIT]
        logger.info("本地菜谱库不足 (%s/%s), 交给 LLM 兜底", len(chosen), len(slots))
        return LocalPlan(hints=hints)

    # ---------- 3. 落库 ----------

    def _day_dates(self, week: WeekMenuGenerate, week_start: date) -> List[date]:
        """以周一起始按顺序对齐日期, 模型给错日期时自动纠正"""
        dates: List[date] = []
        for index, day in enumerate(week.week_menu):
            fallback = week_start + timedelta(days=index)
            parsed: Optional[date] = None
            try:
                parsed = date.fromisoformat((day.date or "").strip())
            except ValueError:
                parsed = None
            if parsed and week_start <= parsed <= week_start + timedelta(days=MAX_MENU_DAYS - 1):
                dates.append(parsed)
            else:
                dates.append(fallback)
        return dates

    async def persist(
        self, ctx: GenerationContext, week: WeekMenuGenerate, source: str = "ai"
    ) -> GenerationOutcome:
        warnings: List[str] = []
        async with session_scope() as session:
            menu_service = MenuService(session)
            recipe_service = RecipeService(session)

            menu = await menu_service.get_editable_menu_for_week(ctx.user_id, ctx.week_start)
            locked_slots = set()
            if menu:
                for existing in list(menu.menu_items):
                    if existing.is_locked:
                        locked_slots.add((existing.meal_date, existing.meal_type))
                        continue
                    await session.delete(existing)
                menu.status = MenuStatus.DRAFT
                menu.source = source
                await session.flush()
            else:
                menu = Menu(
                    user_id=ctx.user_id,
                    week_start_date=ctx.week_start,
                    status=MenuStatus.DRAFT,
                    source=source,
                )
                session.add(menu)
                await session.flush()

            dates = self._day_dates(week, ctx.week_start)
            meal_count = len(locked_slots)
            for index, day in enumerate(week.week_menu):
                meal_date = dates[index]
                for meal_type, meal in (day.meals or {}).items():
                    if meal_type not in VALID_MEAL_TYPES:
                        warnings.append(f"忽略未知餐次: {meal_type}")
                        continue
                    if (meal_date, meal_type) in locked_slots:
                        continue
                    for recipe_data in meal.recipes:
                        if not (recipe_data.name or "").strip():
                            continue
                        hits = find_allergen_hits(recipe_data, ctx.allergens)
                        if hits:
                            warnings.append(f"已剔除含过敏源({', '.join(hits)})的菜品: {recipe_data.name}")
                            continue
                        recipe = await recipe_service.find_or_create_recipe(
                            name=recipe_data.name,
                            cook_minutes=recipe_data.cook_minutes,
                            calories=recipe_data.calories,
                            protein_g=recipe_data.protein_g,
                            carb_g=recipe_data.carb_g,
                            fat_g=recipe_data.fat_g,
                            steps=recipe_data.steps,
                            ingredients=recipe_data.ingredients,
                        )
                        # 必须传 recipe 对象而不是 recipe_id: MenuItem.recipe 是 lazy="selectin",
                        # 只设 id 的话新建对象上该关系仍未加载, 后面 build_snapshots 访问
                        # item.recipe 会触发懒加载, 在异步会话里直接抛 MissingGreenlet。
                        session.add(
                            MenuItem(
                                menu=menu,
                                recipe=recipe,
                                meal_date=meal_date,
                                meal_type=meal_type,
                                estimated_cost=0,
                            )
                        )
                        meal_count += 1
            await session.flush()
            if meal_count == 0:
                raise GenerationError("模型返回的菜单为空, 请重试")

            # 新建的 Menu 在 flush 后 menu_items 仍是"未加载"状态 (selectin 只在查询时生效),
            # 后面 recompute_costs / build_snapshots 一访问就会触发懒加载, 在异步会话里
            # 直接抛 MissingGreenlet。这里显式把集合刷出来 (顺带把每个 item 的 recipe 也带出来)。
            await session.refresh(menu, ["menu_items"])

            cost = await menu_service.recompute_costs(menu)
            nutrition = menu_service.nutrition_report(menu, _health_goal(ctx))
            budget = await menu_service.budget_report(menu, _budget(ctx), cost)
            if not budget.passed:
                warnings.extend(budget.suggestions)
            if cost.unpriced_items:
                warnings.append(f"{cost.unpriced_items} 项食材缺少参考单价, 成本被低估")
            if not nutrition.passed:
                warnings.extend(nutrition.issues[:3])
            menu_id = menu.id

        names = [
            r.name for day in week.week_menu for meal in (day.meals or {}).values() for r in meal.recipes
        ]
        diversity = self.diversity_service.validate(
            names, ctx.history_names, self.settings.menu.diversity_min_score
        )
        return GenerationOutcome(
            menu_id=menu_id,
            week_start=ctx.week_start,
            diversity=diversity,
            nutrition=nutrition,
            cost=cost,
            warnings=warnings,
        )

    # ---------- 4. 编排 ----------

    async def run(self, user_id: int, week_start: date, mode: str = MODE_AUTO) -> GenerationOutcome:
        ctx = await self.prepare(user_id, week_start)
        # 本地优先: 除显式只走模型 (mode=ai) 外, 都先尝试用本地菜谱库编排
        use_local = self.settings.menu.local_first and mode in (MODE_AUTO, MODE_LOCAL)
        plan = await self.compose_from_local(ctx) if use_local else LocalPlan()
        if plan.week is not None:
            return await self.persist(ctx, plan.week, source="local")

        week, _ = await self.call_llm(ctx, hint_names=plan.hints)
        names = [
            r.name for day in week.week_menu for meal in (day.meals or {}).values() for r in meal.recipes
        ]
        first_report = self.diversity_service.validate(
            names, ctx.history_names, self.settings.menu.diversity_min_score
        )
        if not first_report.passed and first_report.overlaps:
            logger.info("多样性不达标, 重生成一次: %s", first_report.issues)
            try:
                second_week, _ = await self.call_llm(
                    ctx, avoid_names=first_report.overlaps, hint_names=plan.hints
                )
                second_names = [
                    r.name
                    for day in second_week.week_menu
                    for meal in (day.meals or {}).values()
                    for r in meal.recipes
                ]
                second_report = self.diversity_service.validate(
                    second_names, ctx.history_names, self.settings.menu.diversity_min_score
                )
            except Exception as exc:  # noqa: BLE001 - 重生成失败则沿用首次结果
                logger.warning("重生成失败, 沿用首次结果: %s", exc)
            else:
                if second_report.score >= first_report.score:
                    week = second_week
        source = "mixed" if plan.hints else "ai"
        return await self.persist(ctx, week, source=source)


def keyword_hits(texts: Sequence[str], keywords: Sequence[str]) -> List[str]:
    """texts 里是否包含任一关键词 (过敏源/忌口判定)"""
    if not keywords:
        return []
    return [word for word in keywords if any(word in text for text in texts)]


def _recipe_haystacks(recipe: Recipe) -> List[str]:
    """菜名 + 食材名, 用于过敏源/忌口的包含判定"""
    names = [recipe.name or ""]
    for row in recipe.recipe_ingredients or []:
        if row.ingredient is not None:
            names.append(row.ingredient.name or "")
    return names


def _per_meal_calories(ctx: GenerationContext) -> Optional[float]:
    if not ctx.target_calories:
        return None
    return float(ctx.target_calories) / max(1, ctx.meals_per_day or 2)


def _score_recipe(
    recipe: Recipe, target_calories: Optional[float], inventory: set, cuisines: Sequence[str]
) -> float:
    """本地候选打分: 热量贴合 50 + 库存命中 30 + 偏好菜系 20"""
    score = 0.0
    if target_calories:
        deviation = abs((recipe.calories or 0) - target_calories) / target_calories
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

    if cuisines and recipe.cuisine and recipe.cuisine in cuisines:
        score += SCORE_CUISINE
    return score


def _to_generate_item(recipe: Recipe) -> RecipeGenerateItem:
    """本地 Recipe -> LLM 同构的生成项, 复用同一条落库路径"""
    ingredients = [
        IngredientItem(name=row.ingredient.name, quantity=row.quantity, unit=row.unit or "")
        for row in recipe.recipe_ingredients or []
        if row.ingredient is not None and row.ingredient.name
    ]
    return RecipeGenerateItem(
        name=recipe.name,
        ingredients=ingredients,
        calories=recipe.calories or 0,
        protein_g=recipe.protein_g or 0.0,
        carb_g=recipe.carb_g or 0.0,
        fat_g=recipe.fat_g or 0.0,
        cook_minutes=recipe.cook_minutes or 20,
        steps=recipe.steps or "",
    )


def _build_week(ctx: GenerationContext, chosen: Dict[Tuple[int, str], Recipe]) -> WeekMenuGenerate:
    days: List[DayGenerateItem] = []
    for day_index in range(MAX_MENU_DAYS):
        meal_date = ctx.week_start + timedelta(days=day_index)
        meals: Dict[str, MealGenerateItem] = {}
        for meal_type in VALID_MEAL_TYPES:
            recipe = chosen.get((day_index, meal_type))
            if recipe is not None:
                meals[meal_type] = MealGenerateItem(recipes=[_to_generate_item(recipe)])
        days.append(
            DayGenerateItem(
                date=str(meal_date),
                day_type="weekend" if meal_date.weekday() >= 5 else "weekday",
                meals=meals,
            )
        )
    return WeekMenuGenerate(week_menu=days)


def _health_goal(ctx: GenerationContext) -> Optional[HealthGoal]:
    """构造一个只读视图供营养校验使用"""
    if not ctx.target_calories:
        return None
    return HealthGoal(
        user_id=ctx.user_id,
        goal_type=None,
        daily_calories=int(ctx.target_calories),
        protein_pct=None,
        carb_pct=None,
        fat_pct=None,
    )


def _budget(ctx: GenerationContext) -> Optional[Budget]:
    if not ctx.weekly_cap and not ctx.weekday_budget:
        return None
    return Budget(
        user_id=ctx.user_id,
        weekday_daily_budget=ctx.weekday_budget or 0.0,
        weekend_daily_budget=ctx.weekend_budget or 0.0,
        weekly_cap=ctx.weekly_cap,
        min_meal_budget=None,
    )


class GenerationWorker:
    """进程内后台 worker: 领取 pending 任务并执行"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self.poll_interval = 1.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.recover_stale_tasks()
        concurrency = max(1, self.settings.menu.generation_concurrency)
        for index in range(concurrency):
            self._tasks.append(asyncio.create_task(self._loop(index), name=f"menu-gen-{index}"))
        logger.info("菜单生成 worker 已启动 (并发 %s)", concurrency)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("菜单生成 worker 已停止")

    async def recover_stale_tasks(self) -> int:
        """进程重启后把僵死的 running 任务标记为失败, 允许用户重试"""
        cutoff = datetime.now() - timedelta(seconds=self.settings.menu.task_timeout_seconds)
        async with session_scope() as session:
            result = await session.execute(
                select(MenuGenerationTask).where(
                    MenuGenerationTask.status == GenerationStatus.RUNNING,
                    MenuGenerationTask.started_at.is_not(None),
                    MenuGenerationTask.started_at < cutoff,
                )
            )
            stale = list(result.scalars().all())
            for task in stale:
                task.status = GenerationStatus.FAILED
                task.error = "服务重启导致任务中断, 请重新生成"
                task.finished_at = datetime.now()
            if stale:
                logger.warning("恢复僵死生成任务 %s 条", len(stale))
        return len(stale)

    async def _claim(self) -> Optional[int]:
        """抢占一条 pending 任务 (MySQL 8 SKIP LOCKED 保证不重复执行)"""
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(MenuGenerationTask)
                    .where(MenuGenerationTask.status == GenerationStatus.PENDING)
                    .order_by(MenuGenerationTask.created_at.asc(), MenuGenerationTask.id.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                task = (await session.execute(stmt)).scalar_one_or_none()
                if task is None:
                    return None
                task.status = GenerationStatus.RUNNING
                task.started_at = datetime.now()
                task.attempts += 1
                return task.id

    async def _execute(self, task_id: int) -> None:
        async with session_scope() as session:
            task = await session.get(MenuGenerationTask, task_id)
            if task is None or task.status != GenerationStatus.RUNNING:
                return
            user_id = task.user_id
            week_start = task.week_start_date
            mode = _payload_mode(task.request_payload)

        try:
            llm = build_fallback_chain(self.settings)
            outcome = await MenuGenerationPipeline(llm, self.settings).run(user_id, week_start, mode)
        except Exception as exc:  # noqa: BLE001 - 失败必须落库可读原因
            logger.exception("生成菜单失败 task=%s", task_id)
            message = str(exc)[:ERROR_MESSAGE_LIMIT] or exc.__class__.__name__
            async with session_scope() as session:
                task = await session.get(MenuGenerationTask, task_id)
                if task:
                    task.status = GenerationStatus.FAILED
                    task.error = message
                    task.finished_at = datetime.now()
            return

        async with session_scope() as session:
            task = await session.get(MenuGenerationTask, task_id)
            if task:
                task.status = GenerationStatus.SUCCEEDED
                task.menu_id = outcome.menu_id
                task.error = None
                task.finished_at = datetime.now()
        logger.info("菜单生成完成 task=%s menu=%s", task_id, outcome.menu_id)

    async def _loop(self, index: int) -> None:
        while self._running:
            try:
                task_id = await self._claim()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 数据库抖动不应杀掉 worker
                logger.exception("领取生成任务失败 worker=%s", index)
                await asyncio.sleep(self.poll_interval * 2)
                continue
            if task_id is None:
                await asyncio.sleep(self.poll_interval)
                continue
            try:
                await self._execute(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("执行生成任务异常 task=%s", task_id)
