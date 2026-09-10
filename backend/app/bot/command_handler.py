"""飞书 Bot 指令处理器"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict

from app.bot.card_builder import CardBuilder

logger = logging.getLogger(__name__)


class CommandHandler:
    """处理飞书消息指令"""

    async def handle_message(self, event: Dict) -> Dict:
        """处理接收到的消息事件"""
        message = event.get("message", {})
        text = message.get("content", "").strip()
        # 去除 JSON 包裹
        try:
            text_obj = json.loads(text)
            if isinstance(text_obj, dict):
                text = text_obj.get("text", text)
        except (json.JSONDecodeError, TypeError):
            pass

        chat_id = event.get("message", {}).get("chat_id", "")
        message_id = message.get("message_id", "")

        # 指令匹配
        if text.startswith("查看今天菜单") or text == "菜单":
            return await self._handle_view_menu(chat_id, message_id)
        elif text.startswith("查看库存"):
            return await self._handle_view_inventory(chat_id, message_id)
        elif text.startswith("添加库存"):
            return await self._handle_add_inventory(text, chat_id, message_id)
        elif text.startswith("完成") or text.startswith("做完"):
            return await self._handle_mark_cooked(text, chat_id, message_id)
        elif text in ("帮助", "help", "?"):
            return await self._handle_help(chat_id, message_id)
        else:
            return await self._handle_unknown(text, chat_id, message_id)

    async def _handle_view_menu(self, chat_id: str, message_id: str) -> Dict:
        return {"msg_type": "text", "content": json.dumps({"text": "今日菜单功能需对接数据库, 请稍候 (Sprint 6+)"})}

    async def _handle_view_inventory(self, chat_id: str, message_id: str) -> Dict:
        return {"msg_type": "text", "content": json.dumps({"text": "库存查看功能需对接数据库, 请稍候 (Sprint 6+)"})}

    async def _handle_add_inventory(self, text: str, chat_id: str, message_id: str) -> Dict:
        # 解析: "添加库存 鸡蛋 10个 保质期7-20"
        return {"msg_type": "text", "content": json.dumps({"text": f"已收到库存添加指令: {text}"})}

    async def _handle_mark_cooked(self, text: str, chat_id: str, message_id: str) -> Dict:
        return {"msg_type": "text", "content": json.dumps({"text": f"已标记完成: {text}"})}

    async def _handle_help(self, chat_id: str, message_id: str) -> Dict:
        help_text = (
            "**AI 菜谱助手 - 支持指令:**\n"
            "- 「查看今天菜单」- 查看当日菜单\n"
            "- 「查看库存」- 查看冰箱库存\n"
            "- 「添加库存 食材 数量 单位」- 添加库存\n"
            "- 「完成 周三晚餐」- 标记某餐已做\n"
            "- 「帮助」- 显示帮助"
        )
        return {"msg_type": "text", "content": json.dumps({"text": help_text})}

    async def _handle_unknown(self, text: str, chat_id: str, message_id: str) -> Dict:
        return {
            "msg_type": "interactive",
            "content": json.dumps(CardBuilder.build_text_card(
                "未知指令",
                f"无法理解「{text}」, 输入「帮助」查看可用指令",
                "grey",
            )),
        }
