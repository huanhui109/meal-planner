"""飞书网页应用扫码登录 - 授权码换用户身份"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

FEISHU_OPEN_BASE = "https://open.feishu.cn/open-apis"
AUTHORIZE_URL = f"{FEISHU_OPEN_BASE}/authen/v1/index"
APP_TOKEN_URL = f"{FEISHU_OPEN_BASE}/auth/v3/app_access_token/internal"
OIDC_TOKEN_URL = f"{FEISHU_OPEN_BASE}/authen/v1/oidc/access_token"
USER_INFO_URL = f"{FEISHU_OPEN_BASE}/authen/v1/user_info"

HTTP_TIMEOUT = 10.0


class FeishuAuthError(Exception):
    """飞书登录流程异常 (对外只暴露可读文案)"""


class FeishuOAuthClient:
    """飞书扫码登录客户端 - 可注入 http client 以便测试 mock"""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._client = client
        self._app_token: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.feishu.app_id and self.settings.feishu.app_secret)

    def build_authorize_url(self, state: str) -> str:
        """构造飞书授权页地址: PC 展示二维码, 手机端唤起飞书 App"""
        if not self.configured:
            raise FeishuAuthError("飞书应用未配置, 请设置 FEISHU_APP_ID / FEISHU_APP_SECRET")
        redirect_uri = self.settings.feishu.redirect_uri
        if not redirect_uri:
            raise FeishuAuthError("飞书回调地址未配置, 请设置 APP__FEISHU__REDIRECT_URI")
        return (
            f"{AUTHORIZE_URL}?app_id={self.settings.feishu.app_id}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&state={quote(state, safe='')}"
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        if self._client is not None:
            response = await self._client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise FeishuAuthError(f"飞书接口返回 HTTP {response.status_code}")
        data = response.json()
        if data.get("code") not in (0, None):
            raise FeishuAuthError(f"飞书接口错误: {data.get('msg', 'unknown')}")
        return data

    async def get_app_access_token(self) -> str:
        """应用级 access_token (带进程内缓存, 有效期由飞书决定)"""
        if self._app_token:
            return self._app_token
        data = await self._request(
            "POST",
            APP_TOKEN_URL,
            json={
                "app_id": self.settings.feishu.app_id,
                "app_secret": self.settings.feishu.app_secret,
            },
        )
        token = data.get("app_access_token", "")
        if not token:
            raise FeishuAuthError("飞书未返回 app_access_token")
        self._app_token = token
        return token

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """授权码换 user_access_token"""
        app_token = await self.get_app_access_token()
        data = await self._request(
            "POST",
            OIDC_TOKEN_URL,
            headers={"Authorization": f"Bearer {app_token}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        payload = data.get("data") or {}
        if not payload.get("access_token"):
            raise FeishuAuthError("飞书未返回用户 access_token")
        return payload

    async def get_user_info(self, user_access_token: str) -> Dict[str, Any]:
        """拉取登录用户资料"""
        data = await self._request(
            "GET",
            USER_INFO_URL,
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        return data.get("data") or {}

    async def login(self, code: str) -> Dict[str, Any]:
        """完整登录流程, 返回归一化后的用户身份"""
        token_payload = await self.exchange_code(code)
        info: Dict[str, Any] = {}
        try:
            info = await self.get_user_info(token_payload["access_token"])
        except FeishuAuthError as exc:
            # 资料拉取失败不阻断登录, 用 token 中的身份兜底
            logger.warning("获取飞书用户资料失败, 使用令牌内身份: %s", exc)

        open_id = info.get("open_id") or token_payload.get("open_id", "")
        if not open_id:
            raise FeishuAuthError("飞书未返回用户 open_id")
        return {
            "open_id": open_id,
            "union_id": info.get("union_id") or token_payload.get("union_id"),
            "name": info.get("name") or "飞书用户",
            "avatar_url": info.get("avatar_url") or info.get("avatar_big") or None,
        }


def get_feishu_oauth_client() -> FeishuOAuthClient:
    """FastAPI 依赖工厂 - 测试中可用 dependency_overrides 替换"""
    return FeishuOAuthClient()
