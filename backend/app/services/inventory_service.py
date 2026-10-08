"""F5 冰箱库存服务 - 入库, 扣减, 缺料比对"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fridge_inventory import ConsumptionRecord, FridgeInventory
from app.models.ingredient import Ingredient
from app.models.menu import Menu, MenuItem
from app.models.recipe import RecipeIngredient
from app.services.ingredient_amount import convert_quantity, normalize_amount
from app.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

QUANTITY_EPSILON = 1e-6


@dataclass
class ConsumptionResult:
    """一次库存扣减的结果"""

    menu_item_id: int
    consumed: List[dict] = field(default_factory=list)
    missing: List[dict] = field(default_factory=list)
    already_cooked: bool = False


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.recipe_service = RecipeService(db)

    # ---------- 查询 ----------

    async def get_current_inventory(self, user_id: int) -> List[FridgeInventory]:
        result = await self.db.execute(
            select(FridgeInventory)
            .where(FridgeInventory.user_id == user_id)
            .order_by(
                FridgeInventory.expiry_date.is_(None),
                FridgeInventory.expiry_date.asc(),
                FridgeInventory.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_expiring_items(self, user_id: int, days: int = 3) -> List[FridgeInventory]:
        target_date = date.today() + timedelta(days=days)
        result = await self.db.execute(
            select(FridgeInventory)
            .where(
                FridgeInventory.user_id == user_id,
                FridgeInventory.expiry_date.is_not(None),
                FridgeInventory.expiry_date <= target_date,
            )
            .order_by(FridgeInventory.expiry_date.asc())
        )
        return list(result.scalars().all())

    async def list_with_ingredient_names(
        self, user_id: int, expiring_within_days: Optional[int] = None
    ) -> List[tuple]:
        """库存列表 (带食材名与品类), 供 Bot/定时任务复用

        expiring_within_days 不为空时只返回该天数内到期的批次。
        """
        stmt = (
            select(FridgeInventory, Ingredient.name, Ingredient.category)
            .join(Ingredient, Ingredient.id == FridgeInventory.ingredient_id)
            .where(FridgeInventory.user_id == user_id)
            .order_by(
                FridgeInventory.expiry_date.is_(None),
                FridgeInventory.expiry_date.asc(),
                FridgeInventory.id.asc(),
            )
        )
        if expiring_within_days is not None:
            deadline = date.today() + timedelta(days=expiring_within_days)
            stmt = stmt.where(
                FridgeInventory.expiry_date.is_not(None),
                FridgeInventory.expiry_date <= deadline,
            )
        result = await self.db.execute(stmt)
        return list(result.all())

    async def get_owned_item(self, menu_item_id: int, user_id: int) -> Optional[MenuItem]:
        """菜单项必须属于当前用户 (越权返回 None)"""
        result = await self.db.execute(
            select(MenuItem)
            .join(Menu, Menu.id == MenuItem.menu_id)
            .where(MenuItem.id == menu_item_id, Menu.user_id == user_id)
        )
        return result.scalar_one_or_none()

    # ---------- 入库 ----------

    async def add_item(
        self,
        user_id: int,
        ingredient_name: str,
        quantity: float,
        unit: str,
        expiry_date: Optional[date] = None,
        source: str = "manual",
    ) -> FridgeInventory:
        amount = normalize_amount(f"{quantity}{unit}" if unit else str(quantity), unit)
        ingredient = await self.recipe_service.get_or_create_ingredient(ingredient_name, unit)
        item = FridgeInventory(
            user_id=user_id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=amount.unit or unit,
            expiry_date=expiry_date,
            source=source,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def delete_item(self, item_id: int, user_id: int) -> bool:
        result = await self.db.execute(
            select(FridgeInventory).where(FridgeInventory.id == item_id, FridgeInventory.user_id == user.id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await self.db.delete(item)
        return True

    async def bulk_add(
        self, user_id: int, items: Sequence[dict]
    ) -> List[dict]:
        """批量入库 (快速补常备食材)。每条 {ingredient_name, quantity, unit}

        逐条走 add_item (自动建食材), 返回已建行的精简信息, 前端据此刷新列表即可。
        """
        created: List[dict] = []
        for it in items:
            item = await self.add_item(
                user_id=user_id,
                ingredient_name=it["ingredient_name"],
                quantity=float(it.get("quantity") or 1),
                unit=it.get("unit") or "份",
            )
            ingredient = await self.db.get(Ingredient, item.ingredient_id)
            created.append(
                {
                    "id": item.id,
                    "ingredient_name": ingredient.name if ingredient else it["ingredient_name"],
                    "quantity": item.quantity,
                    "unit": item.unit,
                }
            )
        await self.db.flush()
        return created

    async def update_item(
        self, item_id: int, user_id: int, quantity: Optional[float] = None, expiry_date: Optional[date] = None
    ) -> Optional[FridgeInventory]:
        result = await self.db.execute(
            select(FridgeInventory).where(FridgeInventory.id == item_id, FridgeInventory.user_id == user_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        if quantity is not None:
            item.quantity = quantity
        if expiry_date is not None:
            item.expiry_date = expiry_date
        await self.db.flush()
        return item

    # ---------- 扣减 ----------

    async def _required_ingredients(self, menu_item: MenuItem) -> List[tuple]:
        """菜单项所需食材: (ingredient_id, name, quantity, unit, standard_unit)"""
        if not menu_item.recipe_id:
            return []
        result = await self.db.execute(
            select(
                Ingredient.id,
                Ingredient.name,
                RecipeIngredient.quantity,
                RecipeIngredient.unit,
                Ingredient.standard_unit,
            )
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id == menu_item.recipe_id)
        )
        return list(result.all())

    async def _stock_rows(
        self, user_id: int, ingredient_ids: Sequence[int]
    ) -> Dict[int, List[FridgeInventory]]:
        grouped: Dict[int, List[FridgeInventory]] = {}
        if not ingredient_ids:
            return grouped
        result = await self.db.execute(
            select(FridgeInventory)
            .where(
                FridgeInventory.user_id == user_id,
                FridgeInventory.ingredient_id.in_(list(ingredient_ids)),
                FridgeInventory.quantity > 0,
            )
            .order_by(
                FridgeInventory.expiry_date.is_(None),
                FridgeInventory.expiry_date.asc(),
                FridgeInventory.id.asc(),
            )
        )
        for row in result.scalars().all():
            grouped.setdefault(row.ingredient_id, []).append(row)
        return grouped

    async def _required_by_recipe(self, recipe_id: int) -> List[tuple]:
        """菜谱所需食材: (ingredient_id, name, quantity, unit, standard_unit)"""
        if not recipe_id:
            return []
        result = await self.db.execute(
            select(
                Ingredient.id,
                Ingredient.name,
                RecipeIngredient.quantity,
                RecipeIngredient.unit,
                Ingredient.standard_unit,
            )
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id == recipe_id)
        )
        return list(result.all())

    async def consume_by_recipe(
    self, recipe_id: int, user_id: int, decision_id: Optional[int] = None
    ) -> Optional[ConsumptionResult]:
        """今日饭决「做完了」: 按菜谱用量扣减库存 (临期优先), 并写入消耗记录

        与 consume_by_menu_item 同一条扣减逻辑, 只是锚点从 menu_item 换成 decision。
        扣减前由调用方负责幂等闸 (decision_log.is_cooked), 这里只认 recipe_id。
        recipe_id 为空 (离线/本地兜底菜谱无库内 recipe) 时返回空结果, 不报错。
        """
        required = await self._required_by_recipe(recipe_id)
        if not required:
            return ConsumptionResult(menu_item_id=0)
        stock = await self._stock_rows(user_id, [row[0] for row in required])
        result = ConsumptionResult(menu_item_id=0)

        for ingredient_id, name, quantity, unit, standard_unit in required:
            rows = stock.get(ingredient_id, [])
            if quantity is None:
                if not rows:
                    result.missing.append(
                        {
                            "ingredient_name": name,
                            "required_quantity": None,
                            "unit": unit,
                            "consumed_quantity": 0.0,
                            "reason": "用量未量化且库存不足",
                        }
                    )
                continue

            remaining = quantity
            for row in rows:
                if remaining <= QUANTITY_EPSILON:
                    break
                need_in_row_unit = convert_quantity(remaining, unit, row.unit)
                if need_in_row_unit is None:
                    continue
                take = min(row.quantity, need_in_row_unit)
                if take <= QUANTITY_EPSILON:
                    continue
                row.quantity = round(row.quantity - take, 6)
                remaining -= convert_quantity(take, row.unit, unit) or 0.0
                self.db.add(
                    ConsumptionRecord(
                        fridge_inventory_id=row.id,
                        menu_item_id=None,
                        decision_id=decision_id,
                        ingredient_id=ingredient_id,
                        unit=row.unit,
                        quantity=round(take, 6),
                    )
                )
                result.consumed.append(
                    {
                        "ingredient_name": name,
                        "inventory_id": row.id,
                        "quantity": round(take, 6),
                        "unit": row.unit,
                    }
                )
                if row.quantity <= QUANTITY_EPSILON:
                    await self.db.delete(row)

            if remaining > QUANTITY_EPSILON:
                result.missing.append(
                    {
                        "ingredient_name": name,
                        "required_quantity": quantity,
                        "unit": unit or standard_unit or "",
                        "consumed_quantity": round(quantity - remaining, 3),
                        "deficit": round(remaining, 3),
                        "reason": "库存不足",
                    }
                )

        await self.db.flush()
        return result

    async def check_missing_ingredients(self, menu_item_id: int, user_id: int) -> List[dict]:
        """比对菜单所需 vs 库存现有, 返回缺口 (不做任何写入)"""
        item = await self.get_owned_item(menu_item_id, user_id)
        if not item:
            return []
        required = await self._required_ingredients(item)
        stock = await self._stock_rows(user_id, [row[0] for row in required])
        missing: List[dict] = []
        for ingredient_id, name, quantity, unit, standard_unit in required:
            available = 0.0
            for row in stock.get(ingredient_id, []):
                converted = convert_quantity(row.quantity, row.unit, unit) if quantity is not None else None
                available += converted if converted is not None else 0.0
            if quantity is None:
                if not stock.get(ingredient_id):
                    missing.append(
                        {
                            "ingredient_name": name,
                            "required_quantity": None,
                            "unit": unit,
                            "in_stock_quantity": 0.0,
                            "deficit": None,
                        }
                    )
                continue
            deficit = round(quantity - available, 3)
            if deficit > QUANTITY_EPSILON:
                missing.append(
                    {
                        "ingredient_name": name,
                        "required_quantity": quantity,
                        "unit": unit or standard_unit or "",
                        "in_stock_quantity": round(available, 3),
                        "deficit": deficit,
                    }
                )
        return missing

    async def consume_by_menu_item(self, menu_item_id: int, user_id: int) -> Optional[ConsumptionResult]:
        """按菜谱用量扣减库存 (临期优先), 并写入消耗记录

        缺料不阻断: 扣到 0 为止, 缺口写进 missing。
        """
        item = await self.get_owned_item(menu_item_id, user_id)
        if not item:
            return None
        if item.is_cooked:
            return ConsumptionResult(menu_item_id=item.id, already_cooked=True)

        required = await self._required_ingredients(item)
        stock = await self._stock_rows(user_id, [row[0] for row in required])
        result = ConsumptionResult(menu_item_id=item.id)

        for ingredient_id, name, quantity, unit, standard_unit in required:
            rows = stock.get(ingredient_id, [])
            if quantity is None:
                if not rows:
                    result.missing.append(
                        {
                            "ingredient_name": name,
                            "required_quantity": None,
                            "unit": unit,
                            "consumed_quantity": 0.0,
                            "reason": "用量未量化且库存不足",
                        }
                    )
                continue

            remaining = quantity
            for row in rows:
                if remaining <= QUANTITY_EPSILON:
                    break
                need_in_row_unit = convert_quantity(remaining, unit, row.unit)
                if need_in_row_unit is None:
                    continue
                take = min(row.quantity, need_in_row_unit)
                if take <= QUANTITY_EPSILON:
                    continue
                row.quantity = round(row.quantity - take, 6)
                remaining -= convert_quantity(take, row.unit, unit) or 0.0
                self.db.add(
                    ConsumptionRecord(
                        fridge_inventory_id=row.id,
                        menu_item_id=item.id,
                        ingredient_id=ingredient_id,
                        unit=row.unit,
                        quantity=round(take, 6),
                    )
                )
                result.consumed.append(
                    {
                        "ingredient_name": name,
                        "inventory_id": row.id,
                        "quantity": round(take, 6),
                        "unit": row.unit,
                    }
                )
                if row.quantity <= QUANTITY_EPSILON:
                    await self.db.delete(row)

            if remaining > QUANTITY_EPSILON:
                result.missing.append(
                    {
                        "ingredient_name": name,
                        "required_quantity": quantity,
                        "unit": unit or standard_unit or "",
                        "consumed_quantity": round(quantity - remaining, 3),
                        "deficit": round(remaining, 3),
                        "reason": "库存不足",
                    }
                )

        item.is_cooked = True
        await self.db.flush()
        return result

    # ---------- 撤销扣减 ----------

    async def restore_by_menu_item(self, menu_item_id: int, user_id: int) -> Optional[dict]:
        """撤销一次「标记已做」: 库存加回去, 并删掉对应的消耗流水

        批次行还在就加回原行; 已经被扣空删除的, 用流水里的 ingredient_id/unit
        重新建一条 (保质期补不回来, 这是可接受的损失 —— 用户自己也会重设)。
        """
        item = await self.get_owned_item(menu_item_id, user_id)
        if not item:
            return None

        rows = (
            (
                await self.db.execute(
                    select(ConsumptionRecord).where(ConsumptionRecord.menu_item_id == item.id)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            item.is_cooked = False
            await self.db.flush()
            return {"item_id": item.id, "restored": [], "skipped": 0}

        restored: List[dict] = []
        skipped = 0
        for record in rows:
            batch = None
            if record.fridge_inventory_id is not None:
                batch = (
                    await self.db.execute(
                        select(FridgeInventory).where(
                            FridgeInventory.id == record.fridge_inventory_id,
                            FridgeInventory.user_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
            if batch is not None:
                batch.quantity = round(batch.quantity + record.quantity, 6)
                name = await self._ingredient_name(batch.ingredient_id)
                restored.append(
                    {
                        "ingredient_name": name,
                        "inventory_id": batch.id,
                        "quantity": round(record.quantity, 6),
                        "unit": batch.unit,
                    }
                )
            elif record.ingredient_id is not None and record.unit:
                created = FridgeInventory(
                    user_id=user_id,
                    ingredient_id=record.ingredient_id,
                    quantity=round(record.quantity, 6),
                    unit=record.unit,
                    source="restore",
                )
                self.db.add(created)
                await self.db.flush()
                name = await self._ingredient_name(record.ingredient_id)
                restored.append(
                    {
                        "ingredient_name": name,
                        "inventory_id": created.id,
                        "quantity": round(record.quantity, 6),
                        "unit": created.unit,
                    }
                )
            else:
                skipped += 1
            await self.db.delete(record)

        item.is_cooked = False
        await self.db.flush()
        return {"item_id": item.id, "restored": restored, "skipped": skipped}

    async def _ingredient_name(self, ingredient_id: int) -> str:
        result = await self.db.execute(select(Ingredient.name).where(Ingredient.id == ingredient_id))
        return result.scalar_one_or_none() or f"食材#{ingredient_id}"
