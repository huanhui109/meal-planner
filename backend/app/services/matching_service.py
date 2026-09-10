"""F3.2 食材-商品匹配服务"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingredient import Ingredient
from app.models.product import ProductMapping

logger = logging.getLogger(__name__)


class MatchingService:
    """食材 -> 小象超市商品匹配"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def match_ingredient(self, ingredient_name: str) -> List[dict]:
        """三级匹配: 精确 -> 模糊 -> 预留 AI 语义"""
        # 1. 检查用户已确认的映射
        result = await self.db.execute(
            select(ProductMapping)
            .join(Ingredient, ProductMapping.ingredient_id == Ingredient.id)
            .where(Ingredient.name == ingredient_name, ProductMapping.user_confirmed == True)
        )
        confirmed = list(result.scalars().all())
        if confirmed:
            return [{"product_id": m.product_id, "match_score": m.match_score, "confirmed": True} for m in confirmed]

        # 2. 模糊匹配 (Sprint 8 完善 AI 语义匹配)
        logger.info(f"No confirmed mapping for {ingredient_name}, returning empty")
        return []

    async def batch_match(self, ingredient_names: List[str]) -> Dict[str, List[dict]]:
        """批量匹配"""
        results = {}
        for name in ingredient_names:
            results[name] = await self.match_ingredient(name)
        return results
