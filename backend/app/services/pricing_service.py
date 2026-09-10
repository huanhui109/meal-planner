"""成本估算 - 按食材参考单价计算菜单成本"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from app.services.ingredient_amount import convert_quantity


@dataclass
class PricedRow:
    """一条待计价用量"""
    ingredient_name: str
    quantity: Optional[float]
    unit: str
    reference_price: Optional[float]
    standard_unit: str = ""


@dataclass
class CostEstimate:
    total: float = 0.0
    priced_items: int = 0
    unpriced_items: int = 0
    unpriced_names: List[str] = field(default_factory=list)


class PricingService:
    """quantity x 参考单价; 单位不可换算时计入未计价, 不臆造价格"""

    def estimate(self, rows: Iterable[PricedRow]) -> CostEstimate:
        estimate = CostEstimate()
        for row in rows:
            if row.reference_price is None or row.quantity is None:
                estimate.unpriced_items += 1
                estimate.unpriced_names.append(row.ingredient_name)
                continue
            target_unit = row.standard_unit or row.unit
            converted = convert_quantity(row.quantity, row.unit, target_unit)
            if converted is None:
                estimate.unpriced_items += 1
                estimate.unpriced_names.append(row.ingredient_name)
                continue
            estimate.total += converted * row.reference_price
            estimate.priced_items += 1
        estimate.total = round(estimate.total, 2)
        return estimate
