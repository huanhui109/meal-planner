"""飞书 Bot 客户端 - 基于 httpx 直接调用 Webhook/API"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class FeishuClient:
    """飞书 Bot 客户端"""

    def __init__(self):
        settings = get_settings()
        self.app_id = settings.feishu.app_id
        self.app_secret = settings.feishu.app_secret
        self.verification_token = settings.feishu.verification_token
        self.encrypt_key = settings.feishu.encrypt_key
        self.default_chat_id = settings.feishu.default_chat_id
        self._token_cache: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        if self._token_cache and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._token_cache

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"获取 token 失败: {data}")
            self._token_cache = data["tenant_access_token"]
            self._token_expires = datetime.now().timestamp() + data.get("expire", 7200) - 60
            return self._token_cache

    async def send_text(self, chat_id: str, text: str) -> Dict[str, Any]:
        """发送文本消息"""
        token = await self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        params = {"receive_id_type": "chat_id"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, params=params)
            return resp.json()

    async def send_card(self, chat_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        """发送交互式卡片消息"""
        token = await self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        params = {"receive_id_type": "chat_id"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, params=params)
            return resp.json()

    async def reply_message(self, message_id: str, text: str) -> Dict[str, Any]:
        """回复消息"""
        token = await self.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            return resp.json()

    def verify_webhook(self, timestamp: str, sign: str) -> bool:
        """验证 Webhook 签名"""
        if not self.encrypt_key:
            return True
        string_to_sign = f"{timestamp}\n{self.encrypt_key}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        calculated_sign = base64.b64encode(hmac_code).decode("utf-8")
        return hmac.compare_digest(calculated_sign, sign)
