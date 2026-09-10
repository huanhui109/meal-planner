"""测试数据构造辅助"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allergy_restriction import AllergyRestriction
from app.models.budget import Budget
from app.models.fridge_inventory import FridgeInventory
from app.models.health_goal import HealthGoal
from app.models.household import Household
from app.models.ingredient import Ingredient
from app.models.menu import Menu, MenuItem, MenuStatus
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User


def week_start_of(day: Optional[date] = None) -> date:
    target = day or date.today()
    return target - timedelta(days=target.weekday())


async def make_user(db: AsyncSession, open_id: str = "ou_test_1", name: str = "测试用户") -> User:
    user = User(open_id=open_id, name=name)
    db.add(user)
    await db.flush()
    return user


async def make_preferences(db: AsyncSession, user_id: int, **overrides) -> None:
    db.add(
        Household(
            user_id=user_id,
            member_count=overrides.get("member_count", 3),
            meals_per_day=2,
            kitchen_equipments=json.dumps(["灶台"], ensure_ascii=False),
            weekday_cook_minutes=30,
            weekend_cook_minutes=60,
        )
    )
    db.add(
        AllergyRestriction(
            user_id=user_id,
            allergens=json.dumps(overrides.get("allergens", ["花生"]), ensure_ascii=False),
            avoid_ingredients=json.dumps(overrides.get("avoid", []), ensure_ascii=False),
            dietary_restrictions="",
        )
    )
    db.add(
        HealthGoal(
            user_id=user_id,
            goal_type="减脂",
            daily_calories=overrides.get("daily_calories", 1800),
            protein_pct=30,
            carb_pct=40,
            fat_pct=30,
        )
    )
    db.add(
        Budget(
            user_id=user_id,
            weekday_daily_budget=35.0,
            weekend_daily_budget=80.0,
            weekly_cap=overrides.get("weekly_cap", 350.0),
            min_meal_budget=8.0,
        )
    )
    await db.flush()


async def make_ingredient(
    db: AsyncSession, name: str, unit: str = "g", price: Optional[float] = 0.02, category: str = "蔬菜"
) -> Ingredient:
    ingredient = Ingredient(name=name, category=category, standard_unit=unit, reference_price=price)
    db.add(ingredient)
    await db.flush()
    return ingredient


async def make_recipe(
    db: AsyncSession,
    name: str,
    ingredient: Ingredient,
    quantity: float,
    unit: str = "g",
    calories: int = 400,
    protein_g: float = 30,
    carb_g: float = 40,
    fat_g: float = 12,
) -> Recipe:
    recipe = Recipe(
        name=name,
        cook_minutes=20,
        calories=calories,
        protein_g=protein_g,
        carb_g=carb_g,
        fat_g=fat_g,
        steps="炒熟即可",
        source="ai_generated",
    )
    db.add(recipe)
    await db.flush()
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=unit,
            amount_text=f"{quantity:g}{unit}",
        )
    )
    await db.flush()
    return recipe


async def make_menu(
    db: AsyncSession,
    user_id: int,
    recipes_by_day: dict,
    week_start: Optional[date] = None,
    status: str = MenuStatus.DRAFT,
    estimated_cost: Optional[float] = None,
) -> Menu:
    """recipes_by_day: {天数偏移: [(recipe, meal_type), ...]}"""
    start = week_start or week_start_of()
    menu = Menu(user_id=user_id, week_start_date=start, status=status)
    db.add(menu)
    await db.flush()
    for offset, meals in recipes_by_day.items():
        for recipe, meal_type in meals:
            db.add(
                MenuItem(
                    menu_id=menu.id,
                    recipe_id=recipe.id,
                    meal_date=start + timedelta(days=offset),
                    meal_type=meal_type,
                    estimated_cost=estimated_cost,
                )
            )
    await db.flush()
    return menu


async def make_stock(
    db: AsyncSession,
    user_id: int,
    ingredient: Ingredient,
    quantity: float,
    unit: str = "g",
    expiry: Optional[date] = None,
) -> FridgeInventory:
    item = FridgeInventory(
        user_id=user_id,
        ingredient_id=ingredient.id,
        quantity=quantity,
        unit=unit,
        expiry_date=expiry,
        source="manual",
    )
    db.add(item)
    await db.flush()
    return item
