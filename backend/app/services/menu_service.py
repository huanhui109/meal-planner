"""F2 菜单服务 - 读取, 编辑, 成本重算与状态流转

生成流程在 generation_service 中; 本服务只负责已有菜单的读写与校验。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.budget import Budget
from app.models.health_goal import HealthGoal
from app.models.ingredient import Ingredient
from app.models.menu import Menu, MenuItem, MenuStatus
from app.models.recipe import Recipe, RecipeIngredient
from app.schemas.recipe import MenuItemReplaceRequest
from app.services.budget_service import BudgetReport, BudgetService
from app.services.nutrition_service import DayNutrition, MealSnapshot, NutritionReport, NutritionService
from app.services.pricing_service import CostEstimate, PricedRow, PricingService
from app.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

MEAL_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2}
MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}


def week_start_of(day: Optional[date] = None) -> date:
    """给定日期所在周的周一"""
    target = day or date.today()
    return target - timedelta(days=target.weekday())


class MenuService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.recipe_service = RecipeService(db)
        self.pricing_service = PricingService()
        self.nutrition_service = NutritionService()
        self.budget_service = BudgetService()

    # ---------- 读取 ----------

    async def get_menu(self, menu_id: int, user_id: int) -> Optional[Menu]:
        """按 ID 读取, 且必须属于当前用户 (越权返回 None -> 404)"""
        result = await self.db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_items))
            .where(Menu.id == menu_id, Menu.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_history(self, user_id: int, weeks: int = 4) -> list[Menu]:
        """历史菜单 (audit T3.3) - 按 week_start_date 倒序取最近 weeks 周"""
        from datetime import date, timedelta

        cutoff = date.today() - timedelta(weeks=weeks)
        result = await self.db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_items))
            .where(Menu.user_id == user_id, Menu.week_start_date >= cutoff)
            .order_by(Menu.week_start_date.desc(), Menu.id.desc())
            .limit(weeks * 2)
        )
        return list(result.scalars().all())

    async def get_current_menu(self, user_id: int) -> Optional[Menu]:
        """最近一份未完成的菜单"""
        result = await self.db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_items))
            .where(
                Menu.user_id == user_id,
                Menu.status.in_((MenuStatus.DRAFT, MenuStatus.CONFIRMED, MenuStatus.ACTIVE)),
            )
            .order_by(Menu.week_start_date.desc(), Menu.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_editable_menu_for_week(self, user_id: int, week_start: date) -> Optional[Menu]:
        """同一周已有草稿/已确认菜单则复用, 避免重复生成"""
        result = await self.db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_items))
            .where(
                Menu.user_id == user_id,
                Menu.week_start_date == week_start,
                Menu.status.in_(MenuStatus.EDITABLE),
            )
            .order_by(Menu.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def history_recipe_names(self, user_id: int, week_start: date, weeks: int) -> List[str]:
        """近 N 周历史菜名, 用于多样性比对"""
        since = week_start - timedelta(weeks=weeks)
        result = await self.db.execute(
            select(Recipe.name)
            .join(MenuItem, MenuItem.recipe_id == Recipe.id)
            .join(Menu, Menu.id == MenuItem.menu_id)
            .where(Menu.user_id == user_id, Menu.week_start_date >= since, Menu.week_start_date < week_start)
        )
        return [row[0] for row in result.all() if row[0]]

    # ---------- 编辑 ----------

    async def replace_item(self, menu: Menu, item: MenuItem, request: MenuItemReplaceRequest) -> MenuItem:
        """替换某一餐的菜品 (用户手动指定新菜)"""
        recipe = await self.recipe_service.find_or_create_recipe(
            name=request.recipe_name,
            cook_minutes=request.cook_minutes,
            calories=request.calories,
            protein_g=request.protein_g,
            carb_g=request.carb_g,
            fat_g=request.fat_g,
            steps=request.steps,
            ingredients=request.recipe_ingredients,
        )
        item.recipe_id = recipe.id
        item.recipe = recipe
        await self.db.flush()
        return item

    async def set_locked(self, item: MenuItem, locked: bool) -> MenuItem:
        item.is_locked = locked
        await self.db.flush()
        return item

    async def confirm(self, menu: Menu) -> Menu:
        menu.status = MenuStatus.CONFIRMED
        await self.db.flush()
        return menu

    # ---------- 成本与校验 ----------

    async def load_priced_rows(self, recipe_ids: Sequence[int]) -> Dict[int, List[PricedRow]]:
        """一次查出多道菜的用量与参考单价"""
        grouped: Dict[int, List[PricedRow]] = {}
        if not recipe_ids:
            return grouped
        result = await self.db.execute(
            select(
                RecipeIngredient.recipe_id,
                Ingredient.name,
                RecipeIngredient.quantity,
                RecipeIngredient.unit,
                Ingredient.reference_price,
                Ingredient.standard_unit,
            )
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id.in_(list(recipe_ids)))
        )
        for recipe_id, name, quantity, unit, ref_price, standard_unit in result.all():
            grouped.setdefault(recipe_id, []).append(
                PricedRow(
                    ingredient_name=name,
                    quantity=quantity,
                    unit=unit or "",
                    reference_price=ref_price,
                    standard_unit=standard_unit or "",
                )
            )
        return grouped

    async def recompute_costs(self, menu: Menu) -> CostEstimate:
        """按当前用量与参考价重算每餐成本并落库"""
        recipe_ids = [item.recipe_id for item in menu.menu_items if item.recipe_id]
        priced = await self.load_priced_rows(recipe_ids)
        total = CostEstimate()
        for item in menu.menu_items:
            rows = priced.get(item.recipe_id or -1, [])
            estimate = self.pricing_service.estimate(rows)
            item.estimated_cost = round(estimate.total, 2) if rows else None
            total.total += estimate.total
            total.priced_items += estimate.priced_items
            total.unpriced_items += estimate.unpriced_items
            total.unpriced_names.extend(estimate.unpriced_names)
        total.total = round(total.total, 2)
        await self.db.flush()
        return total

    def build_snapshots(self, menu: Menu) -> List[MealSnapshot]:
        """把菜单拍平成营养计算所需的快照, 避免 ORM 懒加载"""
        snapshots: List[MealSnapshot] = []
        for item in menu.menu_items:
            recipe = item.recipe
            snapshots.append(
                MealSnapshot(
                    meal_date=item.meal_date,
                    meal_type=item.meal_type,
                    calories=recipe.calories if recipe else None,
                    protein_g=recipe.protein_g if recipe else None,
                    carb_g=recipe.carb_g if recipe else None,
                    fat_g=recipe.fat_g if recipe else None,
                )
            )
        return snapshots

    def nutrition_report(self, menu: Menu, health_goal: Optional[HealthGoal]) -> NutritionReport:
        return self.nutrition_service.validate(
            self.build_snapshots(menu),
            target_calories=health_goal.daily_calories if health_goal else None,
            protein_pct=health_goal.protein_pct if health_goal else None,
            carb_pct=health_goal.carb_pct if health_goal else None,
            fat_pct=health_goal.fat_pct if health_goal else None,
        )

    async def budget_report(
        self, menu: Menu, budget: Optional[Budget], cost: Optional[CostEstimate] = None
    ) -> BudgetReport:
        estimate = cost or await self.recompute_costs(menu)
        daily: List[dict] = []
        for day in self.group_by_day(menu):
            limit = None
            if budget:
                is_weekend = day["weekday"] >= 5
                limit = budget.weekend_daily_budget if is_weekend else budget.weekday_daily_budget
            daily.append({"date": day["date"], "estimated": day["estimated_cost"], "limit": limit})
        limit = budget.weekly_cap if budget and budget.weekly_cap else None
        return self.budget_service.validate(
            total_estimated=estimate.total,
            budget_limit=limit,
            daily=daily,
        )

    # ---------- 序列化 ----------

    def group_by_day(self, menu: Menu) -> List[dict]:
        """按日期分组, 供前端周视图直接渲染"""
        buckets: Dict[date, List[MenuItem]] = {}
        for item in menu.menu_items:
            buckets.setdefault(item.meal_date, []).append(item)
        days: List[dict] = []
        for meal_date in sorted(buckets.keys()):
            items = sorted(
                buckets[meal_date],
                key=lambda i: (MEAL_ORDER.get(i.meal_type, 99), i.id),
            )
            total = sum(i.estimated_cost or 0 for i in items)
            days.append(
                {
                    "date": str(meal_date),
                    "weekday": meal_date.weekday(),
                    "day_type": "weekend" if meal_date.weekday() >= 5 else "weekday",
                    "estimated_cost": round(total, 2),
                    "meals": items,
                }
            )
        return days

    def serialize_recipe(self, recipe: Optional[Recipe], priced_rows: Sequence[PricedRow]) -> Optional[dict]:
        if not recipe:
            return None
        return {
            "id": recipe.id,
            "name": recipe.name,
            "cuisine": recipe.cuisine,
            "difficulty": recipe.difficulty,
            "cook_minutes": recipe.cook_minutes,
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
            "carb_g": recipe.carb_g,
            "fat_g": recipe.fat_g,
            "steps": recipe.steps,
            "source": recipe.source,
            "ingredients": [
                {
                    "name": row.ingredient_name,
                    "quantity": row.quantity,
                    "unit": row.unit,
                    "reference_price": row.reference_price,
                }
                for row in priced_rows
            ],
        }

    def serialize_meal(self, item: MenuItem, priced_rows: Sequence[PricedRow]) -> dict:
        return {
            "id": item.id,
            "meal_type": item.meal_type,
            "meal_label": MEAL_LABELS.get(item.meal_type, item.meal_type),
            "is_locked": item.is_locked,
            "is_cooked": item.is_cooked,
            "cook_mode": item.cook_mode,
            "estimated_cost": item.estimated_cost,
            "recipe": self.serialize_recipe(item.recipe, priced_rows),
        }

    async def serialize(
        self,
        menu: Menu,
        health_goal: Optional[HealthGoal] = None,
        budget: Optional[Budget] = None,
    ) -> dict:
        """完整菜单响应: 天 -> 餐 -> 菜品 -> 食材, 并附营养与预算校验"""
        cost = await self.recompute_costs(menu)
        recipe_ids = [item.recipe_id for item in menu.menu_items if item.recipe_id]
        priced = await self.load_priced_rows(recipe_ids)

        days = []
        for day in self.group_by_day(menu):
            days.append(
                {
                    "date": day["date"],
                    "weekday": day["weekday"],
                    "day_type": day["day_type"],
                    "estimated_cost": day["estimated_cost"],
                    "meals": [
                        self.serialize_meal(item, priced.get(item.recipe_id or -1, []))
                        for item in day["meals"]
                    ],
                }
            )

        nutrition = self.nutrition_report(menu, health_goal)
        budget_report = await self.budget_report(menu, budget, cost)
        return {
            "id": menu.id,
            "user_id": menu.user_id,
            "week_start_date": str(menu.week_start_date),
            "status": menu.status,
            "source": menu.source,
            "created_at": menu.created_at.isoformat() if menu.created_at else None,
            "updated_at": menu.updated_at.isoformat() if menu.updated_at else None,
            "totals": {
                "estimated_cost": cost.total,
                "unpriced_items": cost.unpriced_items,
                "meal_count": len(menu.menu_items),
                "day_count": len(days),
                "cooked_count": sum(1 for i in menu.menu_items if i.is_cooked),
            },
            "nutrition": _serialize_nutrition(nutrition),
            "budget": {
                "passed": budget_report.passed,
                "total_estimated": budget_report.total_estimated,
                "budget_limit": budget_report.budget_limit,
                "over_amount": budget_report.over_amount,
                "suggestions": budget_report.suggestions,
            },
            "days": days,
        }


def _serialize_nutrition(report: NutritionReport) -> dict:
    return {
        "passed": report.passed,
        "days_count": report.days_count,
        "weekly_avg_calories": report.weekly_avg_calories,
        "target_calories": report.target_calories,
        "issues": report.issues,
        "daily": [_serialize_day(day) for day in report.daily_details],
    }


def _serialize_day(day: DayNutrition) -> dict:
    return {
        "date": day.date,
        "calories": day.calories,
        "protein_g": day.protein_g,
        "carb_g": day.carb_g,
        "fat_g": day.fat_g,
        "protein_pct": day.protein_pct,
        "carb_pct": day.carb_pct,
        "fat_pct": day.fat_pct,
        "meal_count": day.meal_count,
    }
