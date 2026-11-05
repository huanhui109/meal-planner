"""WorkBuddy's documented OAuth and local-assistant API, with no ambient redirects."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import httpx

from app.config import Settings, get_settings

API_BASE = "https://www.workbuddy.cn/openapi/v2"
SCOPES = ("user.localassistant.readable", "user.localassistant.invokable")


class WorkBuddyError(Exception):
    def __init__(self, message: str, *, reauthorize: bool = False, transient: bool = False):
        super().__init__(message)
        self.reauthorize = reauthorize
        self.transient = transient


class WorkBuddyClient:
    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._client = client

    @property
    def configured(self) -> bool:
        config = self.settings.workbuddy
        try:
            uri = urlsplit(config.redirect_uri)
            local = uri.hostname in ("localhost", "127.0.0.1", "::1")
            valid_uri = (
                uri.scheme in ("http", "https") and bool(uri.hostname)
                and (uri.scheme == "https" or local)
                and not uri.username and not uri.password and not uri.fragment and not uri.query
            )
        except ValueError:
            valid_uri = False
        return bool(config.client_id and config.client_secret and valid_uri)

    def authorize_url(self, state: str) -> str:
        if not self.configured:
            raise WorkBuddyError("尚未配置 WorkBuddy 应用，请由服务管理员完成配置")
        query = urlencode({
            'response_type': 'code', 'client_id': self.settings.workbuddy.client_id,
            'redirect_uri': self.settings.workbuddy.redirect_uri, 'scope': ' '.join(SCOPES), 'state': state,
        })
        return f"{API_BASE}/authorize?{query}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    timeout=self.settings.workbuddy.timeout_seconds, follow_redirects=False, trust_env=False,
                ) as client:
                    response = await client.request(method, f"{API_BASE}{path}", **kwargs)
            else:
                response = await self._client.request(method, f"{API_BASE}{path}", **kwargs)
        except httpx.HTTPError:
            raise WorkBuddyError("暂时无法连接 WorkBuddy，请稍后重试", transient=True) from None
        if response.status_code in (401, 403):
            raise WorkBuddyError("WorkBuddy 授权失效或权限不足，请重新连接", reauthorize=True)
        if response.status_code == 429:
            raise WorkBuddyError("WorkBuddy 请求较多，正在等待重试", transient=True)
        if response.status_code >= 500:
            raise WorkBuddyError("WorkBuddy 暂时不可用，正在等待重试", transient=True)
        if response.status_code == 400:
            try:
                error = response.json()
            except ValueError:
                error = {}
            if isinstance(error, dict) and error.get("error") == "invalid_grant":
                raise WorkBuddyError("WorkBuddy 授权已过期，请重新连接", reauthorize=True)
        if not 200 <= response.status_code < 300 or len(response.content) > 2_000_000:
            raise WorkBuddyError("WorkBuddy 未接受请求，请检查应用配置和授权")
        try:
            body = response.json()
        except ValueError:
            raise WorkBuddyError("WorkBuddy 返回了无法识别的响应") from None
        if not isinstance(body, dict):
            raise WorkBuddyError("WorkBuddy 返回了无法识别的响应")
        if body.get("error") == "invalid_grant":
            raise WorkBuddyError("WorkBuddy 授权已过期，请重新连接", reauthorize=True)
        if body.get("error") or body.get("code") not in (None, 0):
            raise WorkBuddyError("WorkBuddy 请求未成功，请检查应用权限")
        data = body.get("data", body)
        if not isinstance(data, dict):
            raise WorkBuddyError("WorkBuddy 返回了无法识别的响应")
        return data

    async def token(self, *, code: str = "", refresh_token: str = "") -> dict:
        data = {
            "client_id": self.settings.workbuddy.client_id,
            "client_secret": self.settings.workbuddy.client_secret,
        }
        if refresh_token:
            data.update(grant_type="refresh_token", refresh_token=refresh_token)
        else:
            data.update(grant_type="authorization_code", code=code, redirect_uri=self.settings.workbuddy.redirect_uri)
        result = await self._request("POST", "/token", data=data)
        if (
            not isinstance(result.get("access_token"), str) or not result["access_token"]
            or not isinstance(result.get("expires_in"), int) or not 0 < result["expires_in"] <= 31_536_000
            or not set(SCOPES) <= set(str(result.get("scope", "")).split())
        ):
            raise WorkBuddyError("WorkBuddy 未授予完整的助手调用权限，请检查应用授权范围", reauthorize=True)
        return result

    async def online(self, token: str) -> bool:
        data = await self._request("GET", "/localassistant", headers={"Authorization": f"Bearer {token}"})
        if not isinstance(data.get("online"), bool):
            raise WorkBuddyError("暂时无法确认 WorkBuddy 在线状态")
        return data["online"]

    async def send(self, token: str, content: str) -> str:
        data = await self._request(
            "POST", "/localassistant/message", headers={"Authorization": f"Bearer {token}"},
            json={"content": content, "msg_type": "text"},
        )
        message_id = data.get("message_id")
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200:
            raise WorkBuddyError("WorkBuddy 未返回消息编号，发送状态未确认")
        return message_id

    async def messages(self, token: str, message_id: str) -> list[dict]:
        data = await self._request(
            "GET", "/localassistant/message", headers={"Authorization": f"Bearer {token}"},
            params={"message_id": message_id},
        )
        if not isinstance(data.get("messages"), list):
            raise WorkBuddyError("WorkBuddy 返回了无法识别的消息列表")
        return data["messages"]


def get_workbuddy_client() -> WorkBuddyClient:
    return WorkBuddyClient()
