"""F6.3 补单决策 - 今晚缺什么、要花多少钱、够不够起送价

设计原则 (本期不接商品库, 所以不假装知道真实价格):
  * 价格 = 缺口数量 × ingredient.reference_price, 没有参考价的项如实标为"未计价"
  * 差额不满起送价时, 从"本周后面几餐迟早要买"的缺料里按单价升序挑凑单品
  * 超预算只提示不阻断, 用户自己决定
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from app.services.deeplink_service import PLATFORM_XIAOXIANG, DeeplinkService

logger = logging.getLogger(__name__)

QUANTITY_EPSILON = 1e-6
MAX_TOPUP_ITEMS = 3
# 凑单可以略超起送价, 但不许为了凑单多花一倍的钱 (20 元起送最多凑到 32)
TOPUP_OVERSHOOT_RATIO = 1.6


class OrderService:
    def __init__(self, deeplink: Optional[DeeplinkService] = None):
        self.deeplink = deeplink or DeeplinkService()

    def build_suggestion(
        self,
        shopping: Optional[dict],
        *,
        budget_remaining: Optional[float] = None,
        today_ingredient_ids: Optional[Sequence[int]] = None,
        platform: str = PLATFORM_XIAOXIANG,
    ) -> Optional[dict]:
        """shopping 为 ShoppingService.build 的结果; 没有缺口时返回 None"""
        if not shopping:
            return None
        items = [item for item in shopping.get("items", []) if not item.get("have_enough")]
        if not items:
            return None

        today_ids = set(today_ingredient_ids or [])
        # 今天要用的先买; 今天用不到的归到凑单候选
        if today_ids:
            primary = [item for item in items if item.get("ingredient_id") in today_ids]
            rest = [item for item in items if item.get("ingredient_id") not in today_ids]
        else:
            primary, rest = items, []
        if not primary:
            primary, rest = items, []

        lines: List[dict] = [self._line(item, is_topup=False) for item in primary]
        total = sum(line["estimated_price"] or 0.0 for line in lines)

        min_order = self.deeplink.min_order_amount(platform)
        topup: List[dict] = []
        if min_order > 0 and total < min_order:
            ceiling = min_order * TOPUP_OVERSHOOT_RATIO
            for candidate in sorted(
                (item for item in rest if item.get("quantitative")),
                key=lambda entry: entry.get("reference_price") or 0.0,
            ):
                if total >= min_order or len(topup) >= MAX_TOPUP_ITEMS:
                    break
                line = self._line(candidate, is_topup=True)
                price = line["estimated_price"]
                if price is None or total + price > ceiling:
                    continue
                topup.append(line)
                total += price

        all_lines = lines + topup
        total = round(total, 2)
        unpriced = sum(1 for line in all_lines if line["estimated_price"] is None)
        reaches = min_order <= 0 or total >= min_order
        shortfall = round(max(0.0, min_order - total), 2) if min_order > 0 else 0.0

        return {
            "missing_count": len(primary),
            "items": all_lines,
            "estimated_total": total,
            "unpriced_count": unpriced,
            "min_order_amount": min_order,
            "reaches_min_order": reaches,
            "topup_amount": shortfall,
            "within_budget": None
            if budget_remaining is None
            else total <= budget_remaining + QUANTITY_EPSILON,
            "budget_remaining": None if budget_remaining is None else round(budget_remaining, 2),
            "order_link": self.deeplink.shopping_link([line["name"] for line in lines], platform),
            "links": self.deeplink.multi_item_links([line["name"] for line in lines], platform),
            "miniapp_app_id": self.deeplink.miniapp_app_id(platform),
            "platform": platform,
            "note": self._note(reaches, shortfall, unpriced, platform),
        }

    def _line(self, item: dict, *, is_topup: bool) -> dict:
        quantity = item.get("deficit")
        price = item.get("reference_price")
        estimated: Optional[float] = None
        if item.get("quantitative") and quantity and price:
            estimated = round(float(quantity) * float(price), 2)
        return {
            "ingredient_id": item.get("ingredient_id"),
            "name": item.get("name", ""),
            "category": item.get("category") or "其他",
            "quantity": quantity,
            "unit": item.get("unit") or "",
            "unit_price": price,
            "estimated_price": estimated,
            "quantitative": bool(item.get("quantitative")),
            "is_topup": is_topup,
        }

    def _note(self, reaches: bool, shortfall: float, unpriced: int, platform: str) -> str:
        parts: List[str] = []
        if not reaches and shortfall > 0:
            parts.append(f"还差 ¥{shortfall} 到起送价, 可以再加两样")
        elif reaches and shortfall == 0 and self.deeplink.min_order_amount(platform) > 0:
            parts.append("已够起送价")
        if unpriced:
            parts.append(f"{unpriced} 样食材还没有参考价, 合计不含它们")
        extra = self.deeplink.delivery_note(platform)
        if extra:
            parts.append(extra)
        return "; ".join(parts)
