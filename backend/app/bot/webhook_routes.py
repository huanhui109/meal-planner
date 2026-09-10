"""飞书 Webhook 路由"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request

from app.bot.command_handler import CommandHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["飞书 Bot"])
command_handler = CommandHandler()


@router.post("/webhook")
async def feishu_webhook(request: Request):
    """飞书事件回调入口"""
    body = await request.json()

    # URL Verification
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # Event callback
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message.im.message.receive_v1":
            try:
                result = await command_handler.handle_message(event)
                return result
            except Exception as e:
                logger.error(f"处理消息失败: {e}")
                return {"code": 1, "msg": str(e)}

    return {"code": 0}
