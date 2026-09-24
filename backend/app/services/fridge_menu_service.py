"""按冰箱重排本周 —— 先把手里的食材吃掉, 再补一张采购清单

用户在设置里点「按冰箱重排本周」时走这里。它和 `/menus/generate` 刻意不同:

* 生成(异步, 可能调 LLM): 按营养目标 + 口味 + 预算排一整周, 追求"这周吃得均衡"
* 重排(本服务, 同步):     只用本地菜谱库, 把「这道菜冰箱里的食材够不够」当作第一
                          优先级 —— 能直接做出来的菜先排进去, 凑不满的餐次挑缺得最
                          少的那道, 最后把缺的那部分汇总成这一周的采购清单。

所以打分权重和生成流水线不一样: 这里 SCORE_STOCK 一家独大, 这也是"按冰箱重排"
与"按营养生成"的分水岭。整个过程不调 LLM, 因此同步返回、也不消耗生成额度。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.models.fridge_inventory import FridgeInventory
from app.models.ingredient import Ingredient
from app.models.menu import Menu, MenuItem
from app.models.recipe import Recipe
from app.schemas.serializers import json_list
from app.services.dish_rules import dish_only
from app.services.menu_service import MenuService
from app.services.preference_service import PreferenceService
from app.services.pricing_service import PricedRow, PricingService
from app.services.shopping_service import ShoppingService

logger = logging.getLogger(__name__)

# 最多扫这么多道本地菜谱参与打分 (同步接口, 不能全表捞)
LOCAL_SCAN_LIMIT = 600

# 打分权重 —— 注意这里库存是绝对主角
SCORE_STOCK = 60.0              # 这道菜用到的食材, 冰箱里已经有了多少
COVERAGE_FULL_BONUS = 20.0      # 食材全齐 -> 现在就能做, 额外重奖
SCORE_TASTE = 10.0              # 辣度 + 味型/场景标签贴合
# 暂停(不是废弃), 与 config.py 的 DecideSettings.score_cuisine 同源: recipe.cuisine 存的
# 是菜品分类不是菜系, 396 道只命中 2 道。本处原为 5.0, 归零不影响库存主导的排序。
# 恢复条件: recipe.cuisine 由凌晨 LLM 富集任务标注成真菜系并回填完成, 且 config.py
# 恢复清单里的 6 处一起改 —— 本处是模块级硬编码, 那天最容易漏。
# 恢复目标 5.0(原值) —— **不是 20.0**: 这一路库存是绝对主角, 菜系从来只是小权重,
# 照着另外两条填 20.0 会把它的菜系权重翻 4 倍。恢复前先解决幅度 > random_band 的约束。
SCORE_CUISINE = 0.0
SCORE_BUDGET = 10.0             # 落在每餐预算内 / 超出
BUDGET_OVER_TOLERANCE = 1.2
MAX_REJECTED_RECIPES = 30

DEFAULT_MEALS_PER_DAY = 2
DEFAULT_WEEKDAY_COOK_MINUTES = 30
DEFAULT_WEEKEND_COOK_MINUTES = 60

CST = timezone(timedelta(hours=8))


class FridgeMenuError(Exception):
    """重排无法进行 (例如本周还没有菜单可排)"""


@dataclass
class FridgeRebuildResult:
    """重排摘要 —— 前端拿它告诉用户"清空了多少 / 还得买多少" """

    menu_id: int
    week_start: str
    total_slots: int
    locked_items: int
    changed_items: int
    cookable_now: int        # 冰箱现有食材就能直接做的餐次
    need_shopping: int       # 还差食材的餐次
    unfilled: int            # 本地库挑不出菜的餐次 (保留原样)
    shopping_summary: Dict[str, int]


class FridgeMenuService:
    def __init__(self, db: AsyncSession, settings: Optional[Settings] = None):
        self.db = db
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ 入口

    async def rebuild(self, user_id: int, week_start: str) -> FridgeRebuildResult:
        """把本周每一个未锁定的餐次, 换成"用冰箱现有食材最做得出来"的菜"""
        target_date = parse_week_start(week_start)
        menu = await self._find_menu(user_id, target_date)
        if menu is None:
            raise FridgeMenuError("这周还没有菜单, 先生成一次再回来按冰箱重排")

        prefs = PreferenceService(self.db)
        household = await prefs.get_household(user_id)
        diet = await prefs.get_diet_preference(user_id)
        allergy = await prefs.get_allergy(user_id)
        budget = await prefs.get_budget(user_id)

        avoid = json_list(allergy.avoid_ingredients) if allergy else []
        allergens = json_list(allergy.allergens) if allergy else []
        cuisines = json_list(diet.cuisines) if diet else []
        spice_level = int(diet.spice_level) if diet and diet.spice_level is not None else 2
        taste_tags = split_pref(diet.flavor_preference if diet else None) + json_list(
            diet.scene_tags if diet else None
        )
        meals_per_day = (
            household.meals_per_day if household and household.meals_per_day else DEFAULT_MEALS_PER_DAY
        )

        # 每餐预算: 日预算按当日餐次摊过来
        weekday_budget = weekend_budget = None
        if budget:
            if budget.weekday_daily_budget and budget.weekday_daily_budget > 0:
                weekday_budget = float(budget.weekday_daily_budget) / meals_per_day
            if budget.weekend_daily_budget and budget.weekend_daily_budget > 0:
                weekend_budget = float(budget.weekend_daily_budget) / meals_per_day

        stock = await self._stock_names(user_id)
        recipes = await self._load_candidates()

        items = sorted(menu.menu_items, key=lambda row: (row.meal_date, row.meal_type, row.id))
        # 本周已经占住的名字, 避免同一道菜在一周里出现两次
        used_names: Set[str] = {
            row.recipe.name.strip() for row in items if row.recipe and row.recipe.name
        }

        changed = 0
        locked = 0
        cookable_now = 0
        need_shopping = 0
        unfilled = 0

        for item in items:
            is_weekend = item.meal_date.weekday() >= 5
            if household:
                cook_cap = (
                    household.weekend_cook_minutes if is_weekend else household.weekday_cook_minutes
                )
            else:
                cook_cap = DEFAULT_WEEKEND_COOK_MINUTES if is_weekend else DEFAULT_WEEKDAY_COOK_MINUTES
            meal_budget = weekend_budget if is_weekend else weekday_budget

            if item.is_locked:
                locked += 1
                if item.recipe is not None:
                    if self.is_cookable_now(item.recipe, stock):
                        cookable_now += 1
                    else:
                        need_shopping += 1
                continue

            previous_id = item.recipe_id
            pick = self._pick_best(
                recipes=recipes,
                stock=stock,
                used_names=used_names,
                avoid=avoid,
                allergens=allergens,
                cuisines=cuisines,
                spice_level=spice_level,
                taste_tags=taste_tags,
                cook_cap=cook_cap,
                meal_budget=meal_budget,
            )

            if pick is None:
                # 本地库挑不出符合这一餐条件的菜: 保留原来那道, 不算失败
                unfilled += 1
                if item.recipe is not None:
                    if self.is_cookable_now(item.recipe, stock):
                        cookable_now += 1
                    else:
                        need_shopping += 1
                continue

            if previous_id != pick.id:
                item.recipe_id = pick.id
                item.recipe = pick
                changed += 1
                if previous_id:
                    # 「换一道」的同款去重: 记下被换掉的, 免得下次又换回来
                    item.rejected_recipe_ids = self._append_rejected(
                        item.rejected_recipe_ids, previous_id
                    )

            used_names.add(pick.name.strip())
            if self.is_cookable_now(pick, stock):
                cookable_now += 1
            else:
                need_shopping += 1

        await self.db.flush()
        await MenuService(self.db).recompute_costs(menu)
        await self.db.flush()

        shopping = await ShoppingService(self.db).build(menu.id, user_id) or {}
        summary = shopping.get("summary") or {}

        return FridgeRebuildResult(
            menu_id=menu.id,
            week_start=str(target_date),
            total_slots=len(items),
            locked_items=locked,
            changed_items=changed,
            cookable_now=cookable_now,
            need_shopping=need_shopping,
            unfilled=unfilled,
            shopping_summary={
                "to_buy": int(summary.get("to_buy_count") or 0),
                "have": int(summary.get("have_count") or 0),
                "total": int(summary.get("total_count") or 0),
            },
        )

    # ------------------------------------------------------------------ 数据

    async def _find_menu(self, user_id: int, week_start: date) -> Optional[Menu]:
        # 必须显式预加载: 异步会话里访问未加载的关系会以同步方式发 IO,
        # 直接抛 MissingGreenlet (菜单项和它的菜谱下面都要用到)
        result = await self.db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_items).selectinload(MenuItem.recipe))
            .where(Menu.user_id == user_id, Menu.week_start_date == week_start)
        )
        return result.scalars().first()

    async def _stock_names(self, user_id: int) -> Set[str]:
        """冰箱里还有余量的食材名"""
        rows = await self.db.execute(
            select(Ingredient.name)
            .join(FridgeInventory, FridgeInventory.ingredient_id == Ingredient.id)
            .where(FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0)
        )
        return {name for (name,) in rows.all() if name}

    async def _load_candidates(self) -> Sequence[Recipe]:
        """候选加载。dish_only() 与决策主链路是同一道闸 —— 用冰箱剩菜荐菜同样是
        「饭决」的答案, 不该在这儿漏一条调味品出去"""
        stmt = (
            select(Recipe)
            .options(selectinload(Recipe.recipe_ingredients))
            .where(
                dish_only(),
                Recipe.cook_minutes.is_not(None),
                Recipe.steps.is_not(None),
                Recipe.steps != "",
                Recipe.recipe_ingredients.any(),
            )
            .order_by(Recipe.id.desc())
            .limit(LOCAL_SCAN_LIMIT)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------ 挑选

    def _pick_best(
        self,
        recipes: Sequence[Recipe],
        stock: Set[str],
        used_names: Set[str],
        avoid: List[str],
        allergens: List[str],
        cuisines: List[str],
        spice_level: int,
        taste_tags: List[str],
        cook_cap: int,
        meal_budget: Optional[float],
    ) -> Optional[Recipe]:
        """取分最高的那一道 —— 重排要可预期, 所以这里刻意不做随机"""
        best: Optional[Recipe] = None
        best_score = 0.0
        cap = max(1, int(cook_cap or DEFAULT_WEEKDAY_COOK_MINUTES))
        for recipe in recipes:
            name = (recipe.name or "").strip()
            if not name or name in used_names:
                continue
            if (recipe.cook_minutes or 0) > cap:
                continue
            haystack = [name] + self._ingredient_names(recipe)
            if self._keyword_hits(haystack, allergens) or self._keyword_hits(haystack, avoid):
                continue
            score = self._score(
                recipe,
                stock=stock,
                cuisines=cuisines,
                spice_level=spice_level,
                taste_tags=taste_tags,
                meal_budget=meal_budget,
            )
            if best is None or score > best_score:
                best, best_score = recipe, score
        return best

    def _score(
        self,
        recipe: Recipe,
        stock: Set[str],
        cuisines: List[str],
        spice_level: int,
        taste_tags: List[str],
        meal_budget: Optional[float],
    ) -> float:
        names = self._ingredient_names(recipe)
        score = 0.0
        if names:
            hits = sum(1 for name in names if name in stock)
            coverage = hits / len(names)
            score += SCORE_STOCK * coverage
            if coverage >= 1.0:
                score += COVERAGE_FULL_BONUS
        else:
            score += SCORE_STOCK * 0.5

        if cuisines and recipe.cuisine and recipe.cuisine in cuisines:
            score += SCORE_CUISINE

        # 辣度贴合 (用户 0-5 / 菜谱 0-4, 与 decision_service 同一口径)
        gap = abs((recipe.spice_level or 0) - spice_level) / 4.0
        score += SCORE_TASTE * 0.5 * max(0.0, 1.0 - min(1.0, gap))

        if taste_tags:
            dish_tags = set(json_list(recipe.tags) + json_list(recipe.flavor_tags))
            hits = sum(1 for tag in taste_tags if tag in dish_tags)
            if hits:
                score += SCORE_TASTE * 0.5 * min(1.0, hits / len(taste_tags))

        cost = self._recipe_cost(recipe)
        if meal_budget and cost is not None:
            if cost <= meal_budget:
                score += SCORE_BUDGET
            elif cost <= meal_budget * BUDGET_OVER_TOLERANCE:
                score += SCORE_BUDGET * 0.4
            else:
                score -= SCORE_BUDGET
        return score

    def _recipe_cost(self, recipe: Recipe) -> Optional[float]:
        rows = [
            PricedRow(
                ingredient_name=row.ingredient.name or "",
                quantity=row.quantity,
                unit=row.unit or "",
                reference_price=row.ingredient.reference_price,
                standard_unit=row.ingredient.standard_unit or "",
            )
            for row in (recipe.recipe_ingredients or [])
            if row.ingredient is not None
        ]
        if not rows:
            return None
        estimate = PricingService().estimate(rows)
        return estimate.total if estimate.priced_items else None

    @classmethod
    def is_cookable_now(cls, recipe: Recipe, stock: Set[str]) -> bool:
        """这道菜的食材冰箱里是不是已经齐了 —— 前端用它标注"现在就能做" """
        names = cls._ingredient_names(recipe)
        return bool(names) and all(name in stock for name in names)

    @staticmethod
    def _ingredient_names(recipe: Recipe) -> List[str]:
        return [
            row.ingredient.name
            for row in (recipe.recipe_ingredients or [])
            if row.ingredient is not None and row.ingredient.name
        ]

    @staticmethod
    def _keyword_hits(texts: Sequence[str], keywords: Sequence[str]) -> List[str]:
        if not keywords:
            return []
        return [word for word in keywords if any(word in text for text in texts)]

    def _load_rejected_ids(self, raw: Optional[str]) -> List[int]:
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
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


def parse_week_start(value: str) -> date:
    """'2026-01-05' -> date; 容错交给 ValueError"""
    parts = str(value).split("-")
    if len(parts) != 3:
        raise FridgeMenuError(f"周起始日期格式不对: {value}")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def split_pref(raw: Optional[str]) -> List[str]:
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


__all__ = ["FridgeMenuError", "FridgeMenuService", "FridgeRebuildResult"]
