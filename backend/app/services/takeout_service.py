"""F4 自做 vs 外卖 - 今晚这顿怎么吃

外卖价格没有公开且稳定的接口, 本期不做爬虫, 所以用"用户自己设的参考价":
默认写在 budget.takeout_reference_price, 用户在今日页直接改价会写回那里。

结论不玩玄学, 只有三条规则 (纯函数, 可单测):
  1. 外卖比自做还便宜 -> 推荐外卖
  2. 自做要花的时间明显更久(>=45 分钟)且外卖 35 分钟内能到 -> 两可
  3. 其余情况 -> 推荐自做 (省下的钱 = 外卖价 - 自做价)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.deeplink_service import PLATFORM_MEITUAN, DeeplinkService

logger = logging.getLogger(__name__)

RECOMMENDED_HOMEMADE = "homemade"
RECOMMENDED_TAKEOUT = "takeout"
RECOMMENDED_EITHER = "either"

SLOW_COOK_MINUTES = 45
FAST_DELIVERY_MINUTES = 35


class TakeoutService:
    def __init__(self, deeplink: Optional[DeeplinkService] = None):
        self.deeplink = deeplink or DeeplinkService()

    def compare(
        self,
        *,
        homemade_cost: Optional[float],
        homemade_minutes: Optional[int],
        takeout_price: Optional[float],
        dish_name: str = "",
        daily_budget: Optional[float] = None,
        spent_today: float = 0.0,
        takeout_source: str = "setting",
    ) -> dict:
        cost = round(float(homemade_cost), 2) if homemade_cost else None
        price = round(float(takeout_price), 2) if takeout_price else None
        minutes = int(homemade_minutes) if homemade_minutes else None
        delivery_minutes = self._delivery_minutes(minutes)

        recommended = RECOMMENDED_HOMEMADE
        reasons = []
        if price and cost and price < cost:
            recommended = RECOMMENDED_TAKEOUT
            reasons.append("外卖比自做还便宜")
        elif minutes and minutes >= SLOW_COOK_MINUTES and delivery_minutes <= FAST_DELIVERY_MINUTES:
            recommended = RECOMMENDED_EITHER
            reasons.append(f"自做要 {minutes} 分钟, 今天时间紧的话点外卖也说得过去")

        saving = None
        if price is not None and cost is not None:
            saving = round(price - cost, 2)
            if saving > 0 and recommended == RECOMMENDED_HOMEMADE:
                reasons.append(f"自做省 ¥{saving}")

        remaining = None
        if daily_budget is not None:
            remaining = round(float(daily_budget) - float(spent_today or 0.0), 2)
        after_takeout = None
        if remaining is not None and price is not None:
            after_takeout = round(remaining - price, 2)
            if after_takeout < 0:
                reasons.append(f"点外卖会超当日预算 ¥{abs(after_takeout)}")
            else:
                reasons.append(f"点外卖占当日预算, 还能剩 ¥{after_takeout}")

        return {
            "homemade": {"cost": cost, "minutes": minutes, "label": "自己做饭", "tone": "primary"},
            "takeout": {
                "cost": price,
                "minutes": delivery_minutes,
                "label": "美团外卖",
                "source": takeout_source,
            },
            "saving": saving,
            "recommended": recommended,
            "reasons": reasons,
            "note": " · ".join(reasons[:2]),
            "budget_remaining": remaining,
            "budget_remaining_after_takeout": after_takeout,
            "budget_daily": daily_budget,
            "spent_today": round(float(spent_today or 0.0), 2),
            "link": self.deeplink.search_link(dish_name or "轻食", PLATFORM_MEITUAN),
            "link_label": "跳转美团外卖下单",
            "platform": PLATFORM_MEITUAN,
            "miniapp_app_id": self.deeplink.miniapp_app_id(PLATFORM_MEITUAN),
        }

    @staticmethod
    def _delivery_minutes(cook_minutes: Optional[int]) -> int:
        """外卖没有真实 ETA 数据, 用一个保守的固定值, 不假装是实时估算"""
        return FAST_DELIVERY_MINUTES
