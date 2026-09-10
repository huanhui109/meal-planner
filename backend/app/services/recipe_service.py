"""菜谱服务 - 菜谱与食材用量落库"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingredient import Ingredient
from app.models.recipe import Recipe, RecipeIngredient
from app.schemas.recipe import IngredientItem
from app.services.ingredient_amount import normalize_amount

logger = logging.getLogger(__name__)


class RecipeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_by_name(self, name: str) -> Optional[Recipe]:
        result = await self.db.execute(select(Recipe).where(Recipe.name == name))
        return result.scalar_one_or_none()

    async def get_or_create_ingredient(self, name: str, standard_unit: str = "") -> Ingredient:
        """食材按名称去重, 缺失时自动建 (并发冲突则回读)"""
        clean = (name or "").strip()
        if not clean:
            raise ValueError("食材名称不能为空")
        result = await self.db.execute(select(Ingredient).where(Ingredient.name == clean))
        ingredient = result.scalar_one_or_none()
        if ingredient:
            if not ingredient.standard_unit and standard_unit:
                ingredient.standard_unit = standard_unit
            return ingredient

        ingredient = Ingredient(name=clean, standard_unit=standard_unit or None)
        self.db.add(ingredient)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(select(Ingredient).where(Ingredient.name == clean))
            ingredient = result.scalar_one()
        return ingredient

    async def replace_ingredients(
        self, recipe: Recipe, ingredients: Sequence[IngredientItem]
    ) -> List[RecipeIngredient]:
        """整体覆盖菜谱用量 (LLM 重新生成时调用)"""
        await self.db.execute(
            delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
        )
        rows: List[RecipeIngredient] = []
        for item in ingredients:
            if not (item.name or "").strip():
                continue
            amount = normalize_amount(item.quantity, item.unit or "")
            ingredient = await self.get_or_create_ingredient(
                item.name, amount.unit or (item.unit or "")
            )
            row = RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                quantity=amount.quantity,
                unit=amount.unit,
                amount_text=amount.text or None,
            )
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows

    async def find_or_create_recipe(
        self,
        *,
        name: str,
        cook_minutes: Optional[int] = None,
        calories: Optional[int] = None,
        protein_g: Optional[float] = None,
        carb_g: Optional[float] = None,
        fat_g: Optional[float] = None,
        steps: Optional[str] = None,
        cuisine: Optional[str] = None,
        ingredients: Optional[Sequence[IngredientItem]] = None,
    ) -> Recipe:
        """按菜名复用菜谱, 首次出现时写入完整营养与用量"""
        clean = (name or "").strip()
        if not clean:
            raise ValueError("菜名不能为空")
        recipe = await self.find_by_name(clean)
        if recipe is None:
            recipe = Recipe(name=clean, source="ai_generated")
            self.db.add(recipe)
            await self.db.flush()
            recipe.cook_minutes = cook_minutes
            recipe.calories = calories
            recipe.protein_g = protein_g
            recipe.carb_g = carb_g
            recipe.fat_g = fat_g
            recipe.steps = steps
            recipe.cuisine = cuisine
        else:
            if cook_minutes and not recipe.cook_minutes:
                recipe.cook_minutes = cook_minutes
            if calories and not recipe.calories:
                recipe.calories = calories
            if steps and not recipe.steps:
                recipe.steps = steps
        if ingredients:
            await self.replace_ingredients(recipe, ingredients)
        await self.db.flush()
        return recipe
