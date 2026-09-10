"""飞书 Bot 指令处理器

指令解析部分是纯函数 (parse_*), 可以直接单测; 真正的查询/写入走已有服务层。
Bot 只能通过 open_id 认人: 用户先在网页版扫码登录过一次, 这里才找得到对应账号。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.card_builder import CardBuilder
from app.models.menu import MenuItem
from app.models.user import User
from app.services.inventory_service import InventoryService
from app.services.menu_service import MEAL_LABELS, MenuService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

MEAL_ALIASES = {
    "早餐": "breakfast",
    "早饭": "breakfast",
    "午餐": "lunch",
    "午饭": "lunch",
    "中饭": "lunch",
    "晚餐": "dinner",
    "晚饭": "dinner",
}
WEEKDAY_ALIASES = {
    "周一": 0,
    "星期一": 0,
    "礼拜一": 0,
    "周二": 1,
    "星期二": 1,
    "礼拜二": 1,
    "周三": 2,
    "星期三": 2,
    "礼拜三": 2,
    "周四": 3,
    "星期四": 3,
    "礼拜四": 3,
    "周五": 4,
    "星期五": 4,
    "礼拜五": 4,
    "周六": 5,
    "星期六": 5,
    "礼拜六": 5,
    "周日": 6,
    "周天": 6,
    "星期日": 6,
    "星期天": 6,
    "礼拜天": 6,
}
COMPLETED_KEYWORDS = ("完成", "做完", "已做", "做好了")
EXPIRY_KEYWORDS = ("保质期", "有效期", "到期", "过期")
UNKNOWN_USER_TEXT = "还没找到你的账号。请先在网页版用飞书扫码登录一次, 之后我就能认出你了。"
QUANTITY_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([^\d\s]{0,4})$")
DATE_PATTERN = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
SHORT_DATE_PATTERN = re.compile(r"^(\d{1,2})[-/月](\d{1,2})日?$")


@dataclass
class BotReply:
    """要回复给飞书的内容"""

    msg_type: str
    content: Dict[str, Any]
    consumed: List[dict] = field(default_factory=list)
    missing: List[dict] = field(default_factory=list)

    @staticmethod
    def text(message: str) -> BotReply:
        return BotReply(msg_type="text", content={"text": message})

    @staticmethod
    def card(card: Dict[str, Any]) -> BotReply:
        return BotReply(msg_type="interactive", content=card)

    def to_payload(self) -> Dict[str, Any]:
        """飞书 reply 接口的请求体"""
        return {
            "msg_type": self.msg_type,
            "content": json.dumps(self.content, ensure_ascii=False),
        }


# ---------- 纯解析函数 (可单测) ----------


def parse_command(text: str) -> str:
    """归一化后的指令名"""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in ("菜单", "帮助", "help", "?"):
        return raw
    for keyword in COMPLETED_KEYWORDS:
        if raw.startswith(keyword):
            return "完成"
    if raw.startswith("查看今天菜单") or raw.startswith("今日菜单"):
        return "菜单"
    if raw.startswith("查看库存") or raw.startswith("库存"):
        return "库存"
    if raw.startswith("添加库存") or raw.startswith("入库"):
        return "添加库存"
    return raw


def parse_add_inventory(text: str, today: Optional[date] = None) -> Optional[dict]:
    """解析「添加库存 鸡蛋 10个 保质期 2026-01-20」

    数量与单位可以连写 (10个) 也可以分开写 (2 斤); 保质期可省略。
    解析不出来返回 None, 由调用方回复用法提示。
    """
    today = today or date.today()
    tokens = [token for token in re.split(r"\s+", (text or "").strip()) if token]
    if tokens and tokens[0] in ("添加库存", "入库"):
        tokens = tokens[1:]
    if len(tokens) < 2:
        return None

    name = tokens[0]
    amount: Optional[Tuple[float, str]] = None
    expiry: Optional[date] = None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in EXPIRY_KEYWORDS:
            if index + 1 < len(tokens):
                expiry = _parse_date(tokens[index + 1], today)
                index += 2
                continue
            index += 1
            continue
        if amount is None:
            matched = QUANTITY_PATTERN.match(token)
            if matched:
                quantity = float(matched.group(1))
                unit = matched.group(2)
                index += 1
                if not unit and index < len(tokens) and _is_unit_token(tokens[index], today):
                    unit = tokens[index]
                    index += 1
                amount = (quantity, unit)
                continue
        if expiry is None:
            expiry = _parse_date(token, today)
        index += 1

    if amount is None or amount[0] <= 0:
        return None
    return {"name": name, "quantity": amount[0], "unit": amount[1], "expiry_date": expiry}


def _is_unit_token(token: str, today: date) -> bool:
    """判断一个孤立 token 是不是单位 (斤 / 个 / g ...), 而不是日期或噪音"""
    if not token or len(token) > 4:
        return False
    if token in EXPIRY_KEYWORDS:
        return False
    if token.isdigit():
        return False
    return _parse_date(token, today) is None


def parse_meal_target(text: str, today: Optional[date] = None) -> Tuple[Optional[date], Optional[str]]:
    """解析「完成 周三晚餐」 -> (日期, 餐次)

    周几按"本周"理解 (与菜单的自然周一致); 解析不出来返回 (None, None)。
    """
    today = today or date.today()
    raw = (text or "").strip()
    for keyword in COMPLETED_KEYWORDS:
        if raw.startswith(keyword):
            raw = raw[len(keyword) :]
            break

    meal_type: Optional[str] = None
    for alias, value in MEAL_ALIASES.items():
        if alias in raw:
            meal_type = value
            raw = raw.replace(alias, " ")
            break
    if meal_type is None:
        return None, None

    day: Optional[date] = None
    if "前天" in raw:
        day = today - timedelta(days=2)
    elif "昨天" in raw:
        day = today - timedelta(days=1)
    elif "明天" in raw:
        day = today + timedelta(days=1)
    elif "今天" in raw or "今晚" in raw:
        day = today
    else:
        for alias, weekday in WEEKDAY_ALIASES.items():
            if alias in raw:
                week_start = today - timedelta(days=today.weekday())
                day = week_start + timedelta(days=weekday)
                break
        if day is None:
            for token in re.split(r"[\s,，]+", raw.strip()):
                parsed = _parse_date(token, today)
                if parsed:
                    day = parsed
                    break
    if day is None:
        day = today
    return day, meal_type


def _parse_date(token: str, today: date) -> Optional[date]:
    if not token:
        return None
    matched = DATE_PATTERN.match(token)
    if matched:
        try:
            return date(int(matched.group(1)), int(matched.group(2)), int(matched.group(3)))
        except ValueError:
            return None
    matched = SHORT_DATE_PATTERN.match(token)
    if matched:
        try:
            return date(today.year, int(matched.group(1)), int(matched.group(2)))
        except ValueError:
            return None
    return None


# ---------- 处理器 ----------


class CommandHandler:
    """处理飞书消息指令"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.menu_service = MenuService(db)
        self.inventory_service = InventoryService(db)
        self.user_service = UserService(db)

    async def handle_message(self, event: Dict) -> Optional[BotReply]:
        """返回要回复的内容; 返回 None 表示这条消息应当忽略"""
        message = event.get("message", {}) or {}
        sender_type = (event.get("sender", {}) or {}).get("sender_type", "")
        if sender_type == "app":
            # 机器人自己发的消息, 直接忽略, 避免自问自答死循环
            return None
        if message.get("message_type", "text") != "text":
            return BotReply.text("我暂时只看得懂文字, 可以发「帮助」看看能做什么。")

        text = _extract_text(message.get("content", ""))
        if not text:
            return None

        open_id = ((event.get("sender", {}) or {}).get("sender_id", {}) or {}).get("open_id", "")
        user = await self.user_service.get_by_open_id(open_id) if open_id else None
        if user is None:
            logger.info("收到未注册用户的指令 open_id=%s", open_id or "(空)")
            return BotReply.text(UNKNOWN_USER_TEXT)

        command = parse_command(text)
        today = date.today()
        if command == "菜单":
            return await self._handle_view_menu(user, today)
        if command == "库存":
            return await self._handle_view_inventory(user)
        if command == "添加库存":
            return await self._handle_add_inventory(user, text, today)
        if command == "完成":
            return await self._handle_mark_cooked(user, text, today)
        if command in ("帮助", "help", "?"):
            return self._handle_help()
        return self._handle_unknown(text)

    async def _handle_view_menu(self, user: User, today: date) -> BotReply:
        menu = await self.menu_service.get_current_menu(user.id)
        if menu is None:
            return BotReply.text("这周还没有菜单。到网页版生成一份, 之后随时问我「菜单」。")
        today_items = [item for item in menu.menu_items if item.meal_date == today]
        if not today_items:
            return BotReply.text(
                f"{today.strftime('%m月%d日')} 没有安排餐次, 本周一共 {len(menu.menu_items)} 餐。"
            )

        meals: Dict[str, List[Dict[str, Any]]] = {}
        total_calories = 0
        for item in sorted(today_items, key=lambda i: i.id):
            recipe = item.recipe
            meals.setdefault(item.meal_type, []).append(
                {
                    "name": recipe.name if recipe else "(菜品已删除)",
                    "calories": recipe.calories if recipe else None,
                }
            )
            total_calories += (recipe.calories or 0) if recipe else 0
        card = CardBuilder.build_daily_menu_card(today.strftime("%Y-%m-%d"), meals, total_calories or None)
        return BotReply.card(card)

    async def _handle_view_inventory(self, user: User) -> BotReply:
        rows = await self.inventory_service.list_with_ingredient_names(user.id)
        if not rows:
            return BotReply.text("冰箱是空的。可以发「添加库存 鸡蛋 10个」试试。")
        today = date.today()
        lines = ["当前库存:"]
        for item, name, _category in rows:
            lines.append(f"- {name} {item.quantity:g}{item.unit}{_expiry_suffix(item.expiry_date, today)}")
        return BotReply.text("\n".join(lines))

    async def _handle_add_inventory(self, user: User, text: str, today: date) -> BotReply:
        parsed = parse_add_inventory(text, today)
        if parsed is None:
            return BotReply.text("没看懂。格式示例:「添加库存 鸡蛋 10个 保质期 2026-01-20」(保质期可省略)")
        item = await self.inventory_service.add_item(
            user_id=user.id,
            ingredient_name=parsed["name"],
            quantity=parsed["quantity"],
            unit=parsed["unit"],
            expiry_date=parsed["expiry_date"],
            source="feishu_bot",
        )
        expiry_text = f", 保质期 {parsed['expiry_date']}" if parsed["expiry_date"] else ""
        return BotReply.text(f"已入库: {parsed['name']} {item.quantity:g}{item.unit}{expiry_text}")

    async def _handle_mark_cooked(self, user: User, text: str, today: date) -> BotReply:
        target_date, meal_type = parse_meal_target(text, today)
        if target_date is None or meal_type is None:
            return BotReply.text("没看懂要标记哪一餐。格式示例:「完成 今天晚餐」「完成 周三午餐」")
        menu = await self.menu_service.get_current_menu(user.id)
        if menu is None:
            return BotReply.text("这周还没有菜单, 先去网页版生成一份吧。")
        item = _find_item(menu.menu_items, target_date, meal_type)
        if item is None:
            return BotReply.text(
                f"{target_date.strftime('%m月%d日')} 的{MEAL_LABELS.get(meal_type, meal_type)}没有找到菜单项"
            )
        result = await self.inventory_service.consume_by_menu_item(item.id, user.id)
        if result is None:
            return BotReply.text("这一餐已经不在了, 可能菜单被重新生成过。")
        if result.already_cooked:
            return BotReply.text("这一餐之前已经标记过「已完成」了。")

        title = f"{target_date.strftime('%m月%d日')} {MEAL_LABELS.get(meal_type, meal_type)}"
        if result.missing:
            names = "、".join(item["ingredient_name"] for item in result.missing[:5])
            return BotReply.text(f"{title} 已标记完成。冰箱里还缺: {names}")
        return BotReply.text(f"{title} 已标记完成, 库存已按用量扣减。")

    def _handle_help(self) -> BotReply:
        return BotReply.text(
            "AI 菜谱助手 - 支持的指令:\n"
            "- 菜单: 看今天吃什么\n"
            "- 库存: 看冰箱里有什么\n"
            "- 添加库存 鸡蛋 10个 保质期 2026-01-20\n"
            "- 完成 今天晚餐 / 完成 周三午餐\n"
            "- 帮助: 显示这条说明"
        )

    def _handle_unknown(self, text: str) -> BotReply:
        return BotReply.card(
            CardBuilder.build_text_card(
                "未知指令",
                f"无法理解「{text}」, 输入「帮助」查看可用指令",
                "grey",
            )
        )


def _expiry_suffix(expiry: Optional[date], today: date) -> str:
    """库存行尾的保质期提示"""
    if not expiry:
        return ""
    days_left = (expiry - today).days
    if days_left < 0:
        return f" (已过期 {-days_left} 天)"
    if days_left <= 3:
        return f" (还有 {days_left} 天到期)"
    return f" ({expiry} 到期)"


def _find_item(items: List[MenuItem], target_date: date, meal_type: str) -> Optional[MenuItem]:
    for item in items:
        if item.meal_date == target_date and item.meal_type == meal_type:
            return item
    return None


def _extract_text(content: Any) -> str:
    """飞书文本消息的 content 形如 '{"text": "菜单"}'"""
    if isinstance(content, dict):
        return str(content.get("text", "")).strip()
    raw = str(content or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict):
        return str(parsed.get("text", "")).strip()
    return raw
