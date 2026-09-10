"""F6.3 补单决策服务"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class OrderService:
    """补单决策 - MVP 简化版"""

    async def generate_order_suggestions(
        self,
        missing_ingredients: List[dict],
        budget_remaining: float,
    ) -> dict:
        """生成补单建议"""
        items = []
        total = 0
        for item in missing_ingredients:
            estimated_price = 10.0  # 默认预估单价
            items.append({
                "name": item.get("ingredient_name", ""),
                "required": item.get("deficit", 1),
                "estimated_price": estimated_price,
            })
            total += estimated_price

        return {
            "items": items,
            "estimated_total": total,
            "within_budget": total <= budget_remaining,
        }
