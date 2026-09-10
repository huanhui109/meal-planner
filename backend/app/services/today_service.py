"""今日页聚合 - 一次请求拿到"今天该干什么"

为什么做成聚合接口: 今日页要同时用菜单、采购缺口、补单建议、外卖对比、临期食材、
流程时间线六块数据, 拆成六个请求会让首屏变成一串串行往返, 手机上体验很差。

任何一块数据缺失都不让整页失败:
  * 没有菜单 -> has_menu=False, 前端显示"下一步"空状态卡
  * 没填偏好 -> ready.has_preferences=False
  * 平台/飞书没配置 -> 对应卡片降级或被跳过, 其余照常返回
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.budget import Budget
from app.models.fridge_inventory import FridgeInventory
from app.models.health_goal import HealthGoal
from app.models.household import Household
from app.models.ingredient import Ingredient
from app.services.activity_service import (
    KIND_DAILY_MENU_PUSH,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    ActivityService,
)
from app.services.deeplink_service import PLATFORM_XIAOXIANG, DeeplinkService
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.services.shopping_service import ShoppingService
from app.services.takeout_service import TakeoutService

logger = logging.getLogger(__name__)

EXPIRING_SOON_DAYS = 3
EVENING_CHECK_TIME = time(17, 30)
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class TodayService:
    def __init__(self, db: AsyncSession, settings: Optional[Settings] = None):
        self.db = db
        self.settings = settings or get_settings()
        self.menu_service = MenuService(db)
        self.shopping_service = ShoppingService(db)
        self.activity = ActivityService(db)
        self.deeplink = DeeplinkService(self.settings)
        self.order_service = OrderService(self.deeplink)
        self.takeout_service = TakeoutService(self.deeplink)

    async def build(self, user_id: int, now: Optional[datetime] = None) -> dict:
        current = now or datetime.now()
        today = current.date()

        household = (
            await self.db.execute(select(Household).where(Household.user_id == user_id))
        ).scalar_one_or_none()
        budget = (await self.db.execute(select(Budget).where(Budget.user_id == user_id))).scalar_one_or_none()
        goal = (
            await self.db.execute(select(HealthGoal).where(HealthGoal.user_id == user_id))
        ).scalar_one_or_none()
        menu = await self.menu_service.get_current_menu(user_id)

        payload: Dict[str, object] = {
            "date": today.isoformat(),
            "weekday": today.weekday(),
            "weekday_label": WEEKDAY_LABELS[today.weekday()],
            "day_type": "weekend" if today.weekday() >= 5 else "weekday",
            "generated_at": current.isoformat(timespec="seconds"),
            "ready": {
                "has_preferences": bool(household and budget),
                "has_menu": menu is not None,
            },
            "menu_id": None,
            "menu_status": None,
            "week": None,
            "budget": self._budget_block(budget, today),
            "meals": [],
            "tonight": None,
            "nutrition": None,
            "shopping": None,
            "order": None,
            "takeout": None,
            "expiring": [],
            "timeline": [],
        }
        if menu is None:
            payload["timeline"] = await self._timeline(user_id, current, shopping=None, cooked=0)
            return payload

        menu_data = await self.menu_service.serialize(menu, goal, budget)
        payload["menu_id"] = menu_data["id"]
        payload["menu_status"] = menu_data["status"]
        payload["week"] = {
            "week_start_date": menu_data["week_start_date"],
            "status": menu_data["status"],
            "created_at": menu_data["created_at"],
            "totals": menu_data["totals"],
            "budget": menu_data["budget"],
            "nutrition": menu_data["nutrition"],
        }

        day = next((item for item in menu_data["days"] if item["date"] == today.isoformat()), None)
        meals = list(day["meals"]) if day else []
        payload["meals"] = meals

        shopping = await self.shopping_service.build(menu.id, user_id)
        payload["shopping"] = (
            None
            if shopping is None
            else {
                "to_buy_count": shopping["summary"]["to_buy_count"],
                "have_count": shopping["summary"]["have_count"],
                "items": shopping["items"],
            }
        )

        today_ids = self._today_ingredient_ids(meals, shopping)
        daily_budget = payload["budget"]["daily_budget"]
        spent_today = round(sum(meal.get("estimated_cost") or 0.0 for meal in meals), 2)
        payload["budget"]["spent_today"] = spent_today
        payload["budget"]["remaining_today"] = (
            None if daily_budget is None else round(daily_budget - spent_today, 2)
        )

        payload["nutrition"] = self._today_nutrition(meals, goal)

        payload["order"] = self.order_service.build_suggestion(
            shopping,
            budget_remaining=payload["budget"]["remaining_today"],
            today_ingredient_ids=today_ids,
            platform=PLATFORM_XIAOXIANG,
        )

        tonight = self._tonight_meal(meals)
        expiring = await self._expiring(user_id, meals)
        payload["expiring"] = expiring
        payload["tonight"] = self._tonight_block(
            tonight,
            meals,
            household,
            expiring,
            spent_today=spent_today,
            daily_budget=daily_budget,
            budget=budget,
        )
        # 自做 vs 外卖问的就是"今晚这顿", 所以顶层直接复用今晚的对比结果:
        # 今日页不用为了同一个结论再请求一次, 也不会出现两处算法不一致。
        payload["takeout"] = payload["tonight"]["takeout"] if payload["tonight"] else None

        cooked = sum(1 for meal in meals if meal.get("is_cooked"))
        payload["timeline"] = await self._timeline(user_id, current, shopping=shopping, cooked=cooked)
        return payload

    # ---------- 各数据块 ----------

    @staticmethod
    def _budget_block(budget: Optional[Budget], today: date) -> dict:
        if not budget:
            return {
                "daily_budget": None,
                "weekly_cap": None,
                "spent_today": 0.0,
                "remaining_today": None,
                "takeout_reference_price": None,
            }
        daily = budget.weekend_daily_budget if today.weekday() >= 5 else budget.weekday_daily_budget
        return {
            "daily_budget": round(float(daily), 2),
            "weekly_cap": budget.weekly_cap,
            "spent_today": 0.0,
            "remaining_today": None,
            "takeout_reference_price": round(float(budget.takeout_reference_price or 0.0), 2),
        }

    @staticmethod
    def _ingredient_names(meals: List[dict]) -> set:
        """今天这几餐会用到哪些食材 (按名字)"""
        names = set()
        for meal in meals:
            for ingredient in (meal.get("recipe") or {}).get("ingredients") or []:
                name = (ingredient.get("name") or "").strip()
                if name:
                    names.add(name)
        return names

    @classmethod
    def _today_ingredient_ids(cls, meals: List[dict], shopping: Optional[dict]) -> List[int]:
        """把"今天用到的食材名"映射成 id, 用于把采购缺口分成"今天要买"和"以后要买"

        菜单里只有食材名, 采购清单里才有 id, 所以必须借 shopping 这一层做映射。
        """
        names = cls._ingredient_names(meals)
        if not names or not shopping:
            return []
        return [item["ingredient_id"] for item in shopping.get("items", []) if item.get("name") in names]

    @staticmethod
    def _today_nutrition(meals: List[dict], goal: Optional[HealthGoal]) -> dict:
        calories = round(sum((meal.get("recipe") or {}).get("calories") or 0 for meal in meals))
        protein = round(sum((meal.get("recipe") or {}).get("protein_g") or 0 for meal in meals), 1)
        target = goal.daily_calories if goal else None
        percent = round(calories / target * 100) if target else None
        return {
            "calories": calories,
            "protein_g": protein,
            "target_calories": target,
            "calorie_percent": percent,
            "meal_count": len(meals),
        }

    @staticmethod
    def _tonight_meal(meals: List[dict]) -> Optional[dict]:
        """今晚 = 今天的晚餐; 没有晚餐就取当天最后一餐"""
        if not meals:
            return None
        for meal in meals:
            if meal.get("meal_type") == "dinner":
                return meal
        return meals[-1]

    def _tonight_block(
        self,
        tonight: Optional[dict],
        meals: List[dict],
        household: Optional[Household],
        expiring: List[dict],
        *,
        spent_today: float,
        daily_budget: Optional[float],
        budget: Optional[Budget],
    ) -> Optional[dict]:
        if not tonight:
            return None
        recipe = tonight.get("recipe") or {}
        minutes = recipe.get("cook_minutes")
        members = household.member_count if household else None
        used_expiring = [
            item
            for item in expiring
            if item["ingredient_name"] in {i.get("name") for i in (recipe.get("ingredients") or [])}
        ]
        takeout_price = budget.takeout_reference_price if budget else None
        return {
            "meal_id": tonight.get("id"),
            "meal_type": tonight.get("meal_type"),
            "meal_label": tonight.get("meal_label"),
            "name": recipe.get("name") or "未安排",
            "is_locked": tonight.get("is_locked"),
            "is_cooked": tonight.get("is_cooked"),
            "servings": members,
            "cook_minutes": minutes,
            "calories": recipe.get("calories"),
            "protein_g": recipe.get("protein_g"),
            "estimated_cost": tonight.get("estimated_cost"),
            "step_count": len((recipe.get("steps") or "").splitlines()) if recipe.get("steps") else 0,
            "ingredients": recipe.get("ingredients") or [],
            "steps": recipe.get("steps"),
            "uses_expiring": [
                {"ingredient_name": item["ingredient_name"], "days_left": item["days_left"]}
                for item in used_expiring
            ],
            "takeout": self.takeout_service.compare(
                homemade_cost=tonight.get("estimated_cost"),
                homemade_minutes=minutes,
                takeout_price=takeout_price,
                dish_name=recipe.get("name") or "",
                daily_budget=daily_budget,
                spent_today=spent_today - (tonight.get("estimated_cost") or 0.0),
            ),
        }

    async def _expiring(self, user_id: int, meals: List[dict]) -> List[dict]:
        result = await self.db.execute(
            select(FridgeInventory, Ingredient.name, Ingredient.standard_unit)
            .join(Ingredient, Ingredient.id == FridgeInventory.ingredient_id)
            .where(
                FridgeInventory.user_id == user_id,
                FridgeInventory.quantity > 0,
                FridgeInventory.expiry_date.is_not(None),
            )
            .order_by(FridgeInventory.expiry_date.asc(), FridgeInventory.id.asc())
        )
        today = date.today()
        names_today = set()
        for meal in meals:
            for ingredient in (meal.get("recipe") or {}).get("ingredients") or []:
                names_today.add((ingredient.get("name") or "").strip())
        items: List[dict] = []
        for row, name, unit in result.all():
            days_left = (row.expiry_date - today).days
            if days_left > EXPIRING_SOON_DAYS:
                continue
            items.append(
                {
                    "inventory_id": row.id,
                    "ingredient_id": row.ingredient_id,
                    "ingredient_name": name,
                    "quantity": row.quantity,
                    "unit": row.unit or unit or "",
                    "expiry_date": row.expiry_date.isoformat(),
                    "days_left": days_left,
                    "expiring_soon": True,
                    "used_tonight": name in names_today,
                }
            )
        return items

    async def _timeline(
        self,
        user_id: int,
        now: datetime,
        *,
        shopping: Optional[dict],
        cooked: int,
    ) -> List[dict]:
        return [
            await self._menu_push_entry(user_id),
            self._stock_check_entry(now, shopping),
            self._cook_entry(cooked),
        ]

    async def _menu_push_entry(self, user_id: int) -> dict:
        time_label = self.settings.scheduler.daily_menu_push or "08:00"
        entry: Dict[str, object] = {
            "key": "menu_push",
            "time": time_label,
            "label": "菜单推送至飞书",
            "status": STATUS_SKIPPED,
            "detail": "定时推送未开启",
        }
        if not self.settings.scheduler.enabled:
            return entry
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
            entry["detail"] = "飞书应用未配置"
            return entry
        log = await self.activity.latest_today(user_id, KIND_DAILY_MENU_PUSH)
        if log is None:
            entry["status"] = STATUS_PENDING
            entry["detail"] = f"{time_label} 自动推送"
            return entry
        if log.status == STATUS_SENT:
            entry["status"] = STATUS_SENT
            entry["detail"] = "已送达"
        elif log.status == STATUS_FAILED:
            entry["status"] = STATUS_FAILED
            entry["detail"] = log.detail or "推送失败"
        else:
            entry["status"] = STATUS_SKIPPED
            entry["detail"] = log.detail or "已跳过"
        return entry

    def _stock_check_entry(self, now: datetime, shopping: Optional[dict]) -> dict:
        time_label = self.settings.scheduler.evening_check or "17:30"
        missing = shopping["summary"]["to_buy_count"] if shopping else 0
        done = now.time() >= EVENING_CHECK_TIME
        return {
            "key": "stock_check",
            "time": time_label,
            "label": "库存与菜单双向比对",
            "status": STATUS_SENT if done else STATUS_PENDING,
            "detail": (f"缺 {missing} 样食材" if missing else "库存够用")
            if done
            else f"{time_label} 自动检查一次库存",
        }

    @staticmethod
    def _cook_entry(cooked: int) -> dict:
        return {
            "key": "cook_deduct",
            "time": "",
            "label": "做饭完成后自动扣减库存",
            "status": STATUS_SENT if cooked else STATUS_PENDING,
            "detail": f"{cooked} 餐已做完, 库存已扣减" if cooked else "做完点一下「标记已做」就会自动扣",
        }
