"""飞书 Bot 客户端 - 基于 httpx 调用消息与令牌接口

可注入 http client (client=...), 测试里不用真的发请求。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

OPEN_BASE = "https://open.feishu.cn/open-apis"
TENANT_TOKEN_URL = f"{OPEN_BASE}/auth/v3/tenant_access_token/internal"
MESSAGE_URL = f"{OPEN_BASE}/im/v1/messages"

HTTP_TIMEOUT = 10.0
TOKEN_SAFETY_WINDOW = 60.0


class FeishuClientError(RuntimeError):
    """飞书接口调用失败 (对外只暴露可读文案)"""


class FeishuClient:
    """飞书 Bot 客户端"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        default_chat_id: Optional[str] = None,
    ):
        settings = settings or get_settings()
        # 显式传入的凭证优先: 每个用户可以用自己的飞书应用 (见 user_feishu_config)
        self.app_id = app_id if app_id is not None else settings.feishu.app_id
        self.app_secret = app_secret if app_secret is not None else settings.feishu.app_secret
        self.verification_token = settings.feishu.verification_token
        self.encrypt_key = settings.feishu.encrypt_key
        self.default_chat_id = (
            default_chat_id if default_chat_id is not None else settings.feishu.default_chat_id
        )
        self._client = client
        self._token_cache: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        """没有 app_id / app_secret 时无法调用任何飞书接口"""
        return bool(self.app_id and self.app_secret)

    # ---------- 基础请求 ----------

    async def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        if not self.configured:
            raise FeishuClientError("飞书应用未配置, 请设置 FEISHU_APP_ID / FEISHU_APP_SECRET")
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise FeishuClientError(f"调用飞书接口失败: {exc}") from exc
        if response.status_code >= 400:
            raise FeishuClientError(f"飞书接口返回 HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise FeishuClientError("飞书接口返回的不是 JSON") from exc
        if data.get("code") not in (0, None):
            raise FeishuClientError(f"飞书接口错误: {data.get('msg') or data.get('code')}")
        return data

    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token (进程内缓存)"""
        now = time.time()
        if self._token_cache and now < self._token_expires_at:
            return self._token_cache

        data = await self._request(
            "POST",
            TENANT_TOKEN_URL,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuClientError("飞书未返回 tenant_access_token")
        expire = float(data.get("expire") or 7200)
        self._token_cache = token
        self._token_expires_at = now + max(expire - TOKEN_SAFETY_WINDOW, 0.0)
        return token

    async def _send(
        self, receive_id: str, msg_type: str, content: Any, receive_id_type: str
    ) -> Dict[str, Any]:
        if not receive_id:
            raise FeishuClientError("缺少接收方 ID")
        token = await self.get_tenant_access_token()
        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        }
        return await self._request(
            "POST",
            MESSAGE_URL,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": receive_id_type},
        )

    # ---------- 对外发送 ----------

    async def send_text(self, receive_id: str, text: str, receive_id_type: str = "chat_id") -> Dict[str, Any]:
        """发文本消息 (receive_id_type 可为 chat_id / open_id / user_id)"""
        return await self._send(receive_id, "text", {"text": text}, receive_id_type)

    async def send_card(
        self, receive_id: str, card: Dict[str, Any], receive_id_type: str = "chat_id"
    ) -> Dict[str, Any]:
        """发交互式卡片 (receive_id_type 可为 chat_id / open_id / user_id)"""
        return await self._send(receive_id, "interactive", card, receive_id_type)

    async def reply(self, message_id: str, msg_type: str, content: Any) -> Dict[str, Any]:
        """回复某条消息 (用户主动发消息后 1 小时内可用)"""
        if not message_id:
            raise FeishuClientError("缺少 message_id, 无法回复")
        token = await self.get_tenant_access_token()
        payload = {
            "msg_type": msg_type,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        }
        return await self._request(
            "POST",
            f"{MESSAGE_URL}/{message_id}/reply",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )


def get_feishu_bot_client() -> FeishuClient:
    """FastAPI 依赖工厂 - 测试中可用 dependency_overrides 替换"""
    return FeishuClient()
