"""F3.3 采购清单 - 菜单所需食材与冰箱库存的差集

本期不接商超价格, 只回答"还差什么、差多少"。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fridge_inventory import FridgeInventory
from app.models.ingredient import Ingredient
from app.models.recipe import RecipeIngredient
from app.services.ingredient_amount import convert_quantity
from app.services.menu_service import MenuService

logger = logging.getLogger(__name__)

QUANTITY_EPSILON = 1e-6


class ShoppingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.menu_service = MenuService(db)

    async def _required(self, recipe_ids: List[int]) -> Dict[int, dict]:
        """汇总菜单所需食材到标准单位"""
        aggregated: Dict[int, dict] = {}
        if not recipe_ids:
            return aggregated
        result = await self.db.execute(
            select(
                Ingredient.id,
                Ingredient.name,
                Ingredient.category,
                Ingredient.standard_unit,
                RecipeIngredient.quantity,
                RecipeIngredient.unit,
            )
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id.in_(recipe_ids))
        )
        for ingredient_id, name, category, standard_unit, quantity, unit in result.all():
            target = standard_unit or unit or ""
            entry = aggregated.setdefault(
                ingredient_id,
                {
                    "ingredient_id": ingredient_id,
                    "name": name,
                    "category": category or "其他",
                    "unit": target,
                    "required_quantity": 0.0,
                    "quantitative": True,
                },
            )
            if quantity is None:
                entry["quantitative"] = False
                continue
            converted = convert_quantity(quantity, unit or "", target)
            if converted is None:
                entry["quantitative"] = False
                continue
            entry["required_quantity"] += converted
        return aggregated

    async def _stock(self, user_id: int, ingredient_ids: List[int]) -> Dict[int, List[Tuple[float, str]]]:
        grouped: Dict[int, List[Tuple[float, str]]] = {}
        if not ingredient_ids:
            return grouped
        result = await self.db.execute(
            select(FridgeInventory.ingredient_id, FridgeInventory.quantity, FridgeInventory.unit)
            .where(
                FridgeInventory.user_id == user_id,
                FridgeInventory.ingredient_id.in_(ingredient_ids),
                FridgeInventory.quantity > 0,
            )
        )
        for ingredient_id, quantity, unit in result.all():
            grouped.setdefault(ingredient_id, []).append((quantity, unit or ""))
        return grouped

    async def build(self, menu_id: int, user_id: int) -> Optional[dict]:
        """生成采购清单, 菜单不属于当前用户时返回 None"""
        menu = await self.menu_service.get_menu(menu_id, user_id)
        if not menu:
            return None

        recipe_ids = [item.recipe_id for item in menu.menu_items if item.recipe_id]
        required = await self._required(recipe_ids)
        stock = await self._stock(user_id, list(required.keys()))

        items: List[dict] = []
        for ingredient_id, entry in required.items():
            available = 0.0
            unit_mismatch = False
            for quantity, unit in stock.get(ingredient_id, []):
                converted = convert_quantity(quantity, unit, entry["unit"])
                if converted is None:
                    unit_mismatch = True
                    continue
                available += converted
            if entry["quantitative"]:
                deficit = max(0.0, entry["required_quantity"] - available)
                have_enough = deficit <= QUANTITY_EPSILON
            else:
                deficit = None
                have_enough = available > 0
            items.append(
                {
                    **entry,
                    "required_quantity": round(entry["required_quantity"], 3)
                    if entry["quantitative"]
                    else None,
                    "in_stock_quantity": round(available, 3),
                    "deficit": round(deficit, 3) if deficit is not None else None,
                    "have_enough": have_enough,
                    "unit_mismatch": unit_mismatch,
                }
            )

        items.sort(key=lambda i: (i["have_enough"], i["category"], i["name"]))
        to_buy = [item for item in items if not item["have_enough"]]
        return {
            "menu_id": menu.id,
            "week_start_date": str(menu.week_start_date),
            "summary": {
                "total_count": len(items),
                "to_buy_count": len(to_buy),
                "have_count": len(items) - len(to_buy),
                "unit_mismatch_count": sum(1 for item in items if item["unit_mismatch"]),
            },
            "items": items,
        }
