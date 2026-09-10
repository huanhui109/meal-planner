"""F2.3 预算约束"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_TOLERANCE = 0.05


@dataclass
class BudgetReport:
    passed: bool
    total_estimated: float
    budget_limit: float
    over_amount: float = 0.0
    per_day: List[dict] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class BudgetService:
    """按日预算与周上限校验, 超支只告警不阻断生成"""

    def validate(
        self,
        total_estimated: float,
        budget_limit: Optional[float],
        tolerance: float = DEFAULT_TOLERANCE,
        daily: Optional[List[dict]] = None,
    ) -> BudgetReport:
        daily = daily or []
        suggestions: List[str] = []

        for entry in daily:
            limit = entry.get("limit")
            spent = entry.get("estimated", 0.0)
            if limit and spent > limit * (1 + tolerance):
                suggestions.append(
                    f"{entry.get('date')} 预估 ¥{spent:.0f} 超出当日预算 ¥{limit:.0f}"
                )

        if not budget_limit:
            return BudgetReport(
                passed=True,
                total_estimated=round(total_estimated, 2),
                budget_limit=0.0,
                per_day=daily,
                suggestions=suggestions,
            )

        passed = total_estimated <= budget_limit * (1 + tolerance)
        over_amount = max(0.0, total_estimated - budget_limit)
        if not passed:
            over_pct = over_amount / budget_limit * 100 if budget_limit else 0.0
            suggestions.append(
                f"预估总花费 ¥{total_estimated:.0f} 超出预算 ¥{budget_limit:.0f} 约 {over_pct:.0f}%"
            )
            suggestions.append("建议: 将高价食材替换为平价替代 (如牛肉 -> 鸡胸肉)")

        return BudgetReport(
            passed=passed,
            total_estimated=round(total_estimated, 2),
            budget_limit=round(budget_limit, 2),
            over_amount=round(over_amount, 2),
            per_day=daily,
            suggestions=suggestions,
        )
