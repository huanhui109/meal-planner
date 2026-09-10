"""微信小程序登录 - code2session 换取 openid

小程序端 `wx.login()` 拿到临时 code, 后端用它换 openid; openid 是小程序内的
用户唯一标识, 全局唯一且不会变, 所以可以直接当账号主键用。

与飞书登录的关系: 两者并存不绑定。飞书用户写 `open_id = "ou_..."`,
微信用户写 `open_id = "wechat:<openid>"`, 靠前缀分命名空间 (本地开发登录用
`dev:` 前缀同理)。这样同一个自然人用两种方式登录会得到两个账号, 本期不做合并。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
HTTP_TIMEOUT = 10.0

OPEN_ID_PREFIX = "wechat:"


class WechatAuthError(Exception):
    """微信登录流程异常 (对外只暴露可读文案)"""


class WechatMiniClient:
    """微信小程序登录客户端 - 可注入 http client 以便测试 mock"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_settings()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.settings.wechat.app_id and self.settings.wechat.app_secret)

    async def code2session(self, code: str) -> Dict[str, Any]:
        """临时 code 换 openid / session_key

        微信这个接口的失败不是靠 HTTP 状态码, 而是 200 响应体里的 errcode,
        所以两种都要判。
        """
        if not self.configured:
            raise WechatAuthError("微信小程序未配置, 请设置 APP__WECHAT__APP_ID / APP__WECHAT__APP_SECRET")
        if not code:
            raise WechatAuthError("缺少微信登录 code")

        params = {
            "appid": self.settings.wechat.app_id,
            "secret": self.settings.wechat.app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        url = f"{CODE2SESSION_URL}?{urlencode(params)}"
        try:
            if self._client is not None:
                response = await self._client.get(url)
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.get(url)
        except httpx.HTTPError as exc:
            raise WechatAuthError(f"微信接口请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise WechatAuthError(f"微信接口返回 HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise WechatAuthError("微信接口返回了非 JSON 响应") from exc

        errcode = data.get("errcode")
        if errcode:
            raise WechatAuthError(f"微信登录失败({errcode}): {data.get('errmsg', 'unknown')}")
        openid = data.get("openid")
        if not openid:
            raise WechatAuthError("微信未返回 openid")
        return data

    async def login(self, code: str) -> Dict[str, Any]:
        """完整登录流程, 返回归一化后的用户身份"""
        data = await self.code2session(code)
        return {
            "open_id": f"{OPEN_ID_PREFIX}{data['openid']}",
            "union_id": data.get("unionid"),
            "name": "微信用户",
            "avatar_url": None,
        }


def get_wechat_mini_client() -> WechatMiniClient:
    """FastAPI 依赖工厂 - 测试中可用 dependency_overrides 替换"""
    return WechatMiniClient()
