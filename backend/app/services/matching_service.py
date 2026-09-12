"""F3.2 食材-商品匹配服务"""

from __future__ import annotations

import logging
from typing import Dict, List

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
        """精确匹配: 只认用户确认过的 ProductMapping

        只实现第一级。模糊匹配与 AI 语义匹配属二期 (V3.x), 未实现前直接返回空 ——
        调用方按「命中为空即走兜底」处理, 不要假设这里会返回候选。
        """
        # 1. 检查用户已确认的映射
        result = await self.db.execute(
            select(ProductMapping)
            .join(Ingredient, ProductMapping.ingredient_id == Ingredient.id)
            .where(Ingredient.name == ingredient_name, ProductMapping.user_confirmed.is_(True))
        )
        confirmed = list(result.scalars().all())
        if confirmed:
            return [
                {"product_id": m.product_id, "match_score": m.match_score, "confirmed": True}
                for m in confirmed
            ]

        # 2. 模糊匹配 / AI 语义匹配属二期 (V3.x), 当前未实现, 无 confirmed 映射即视为未命中
        logger.info("No confirmed mapping for %s, returning empty", ingredient_name)
        return []

    async def batch_match(self, ingredient_names: List[str]) -> Dict[str, List[dict]]:
        """批量匹配"""
        results = {}
        for name in ingredient_names:
            results[name] = await self.match_ingredient(name)
        return results
