"""飞书 Webhook 路由

处理顺序 (任一步失败都必须给出可读日志, 不把飞书页面上的"回调失败"甩给用户):
  1. 校验签名 (配了 encrypt_key 就必须带 X-Lark-Signature)
  2. 配了 encrypt_key 时事件体是密文, 先解密
  3. 校验 verification_token
  4. url_verification 同步回 challenge; 事件回调则按 event_id 去重后立即返回 200
  5. 真正的处理与回复放到后台任务里做 (飞书要求 1 秒内响应, 否则会重推)
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import JSONResponse

from app.bot.command_handler import CommandHandler
from app.bot.feishu_client import FeishuClient, FeishuClientError, get_feishu_bot_client
from app.bot.webhook_security import (
    decrypt_event,
    is_encrypted,
    verify_signature,
    verify_token,
)
from app.database import session_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["飞书 Bot"])

MESSAGE_EVENT_TYPE = "im.message.receive_v1"
MAX_REMEMBERED_EVENTS = 512


class _EventDeduplicator:
    """飞书在超时后会重推同一个事件, 用 event_id 挡掉重复回复 (单进程内足够)"""

    def __init__(self, maxlen: int = MAX_REMEMBERED_EVENTS):
        self._order: deque = deque(maxlen=maxlen)
        self._seen: Set[str] = set()
        self._maxlen = maxlen

    def first_time(self, event_id: str) -> bool:
        if not event_id:
            return True
        if event_id in self._seen:
            return False
        if len(self._order) == self._maxlen:
            self._seen.discard(self._order[0])
        self._order.append(event_id)
        self._seen.add(event_id)
        return True


_event_deduplicator = _EventDeduplicator()


def _reject(reason: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"code": 1, "message": reason})


@router.post("/webhook")
async def feishu_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    client: FeishuClient = Depends(get_feishu_bot_client),
):
    """飞书事件回调入口"""
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        logger.warning("飞书回调请求体不是合法 JSON")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"code": 1, "message": "请求体不是合法 JSON"}
        )
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"code": 1, "message": "请求体必须是 JSON 对象"}
        )

    if not verify_signature(request.headers, client.encrypt_key):
        return _reject("签名校验失败")

    if is_encrypted(body):
        try:
            body = decrypt_event(body["encrypt"], client.encrypt_key)
        except ValueError as exc:
            logger.warning("飞书事件体解密失败: %s", exc)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": 1, "message": f"事件体解密失败: {exc}"},
            )

    if not verify_token(body, client.verification_token):
        return _reject("token 校验失败")

    # URL 校验必须同步回 challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    if body.get("type") != "event_callback":
        logger.info("忽略未知回调类型: %s", body.get("type"))
        return {"code": 0}

    event = body.get("event") or {}
    header = body.get("header") or {}
    event_id = str(header.get("event_id") or event.get("event_id") or "")
    if not _event_deduplicator.first_time(event_id):
        logger.info("重复的飞书事件, 已忽略 event_id=%s", event_id)
        return {"code": 0}

    if event.get("type") != MESSAGE_EVENT_TYPE:
        logger.info("忽略未处理的事件类型: %s", event.get("type"))
        return {"code": 0}

    background_tasks.add_task(_handle_message_event, event, client)
    return {"code": 0}


async def _handle_message_event(event: Dict[str, Any], client: FeishuClient) -> None:
    """在后台任务里查库并回复 (失败只写日志, 不影响已经返回的 200)"""
    message = event.get("message") or {}
    message_id = str(message.get("message_id") or "")
    try:
        async with session_scope() as session:
            reply = await CommandHandler(session).handle_message(event)
    except Exception:  # noqa: BLE001 - 后台任务不能把异常抛给事件循环
        logger.exception("处理飞书消息失败 message_id=%s", message_id)
        return
    if reply is None:
        logger.info("飞书消息无需回复 message_id=%s", message_id)
        return
    if not client.configured:
        logger.warning("飞书应用未配置, 跳过回复 (内容: %s)", _preview(reply))
        return
    try:
        await client.reply(message_id, reply.msg_type, reply.content)
    except FeishuClientError as exc:
        logger.warning("回复飞书消息失败 message_id=%s: %s", message_id, exc)


def _preview(reply) -> Optional[str]:
    text = reply.content.get("text") if isinstance(reply.content, dict) else None
    return text[:80] if text else reply.msg_type
