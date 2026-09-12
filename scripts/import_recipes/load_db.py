"""幂等落库 - 不走裸 SQL, 直接复用菜谱服务写入

与 ``data/sql/recipes_seed.sql`` 等价, 但走 ORM (复用 ``RecipeService`` 的去重与
用量归一化逻辑)。已存在的菜名直接跳过, 因此可重复执行。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import async_session_factory, close_db  # noqa: E402
from app.schemas.recipe import IngredientItem  # noqa: E402
from app.services.recipe_service import RecipeService  # noqa: E402

from .normalize import RecipeRecord  # noqa: E402

logger = logging.getLogger(__name__)


async def load_records(records: List[RecipeRecord]) -> dict:
    created = skipped = failed = 0
    async with async_session_factory() as session:
        service = RecipeService(session)
        for record in records:
            try:
                if await service.find_by_name(record.name):
                    skipped += 1
                    continue
                items = [
                    IngredientItem(name=item.name, quantity=item.quantity, unit=item.unit)
                    for item in record.ingredients
                    if item.name
                ]
                recipe = await service.find_or_create_recipe(
                    name=record.name,
                    cook_minutes=record.cook_minutes,
                    calories=record.calories,
                    protein_g=record.protein_g,
                    carb_g=record.carb_g,
                    fat_g=record.fat_g,
                    steps=record.steps or None,
                    cuisine=record.cuisine,
                    ingredients=items or None,
                )
                recipe.source = record.source
                recipe.difficulty = record.difficulty
                await session.commit()
                created += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮整批
                await session.rollback()
                failed += 1
                logger.warning("落库失败 %s: %s", record.name, exc)
    await close_db()
    return {"created": created, "skipped": skipped, "failed": failed}
