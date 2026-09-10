"""微信小程序登录客户端单元测试

重点: 微信 jscode2session 的失败**不是**靠 HTTP 状态码, 而是 200 响应体里的
errcode。只判 HTTP 就会把"code 已过期"当成登录成功, 拿到一个没有 openid 的响应。
"""
from __future__ import annotations

import httpx
import pytest
from app.auth.wechat_oauth import (
    CODE2SESSION_URL,
    WechatAuthError,
    WechatMiniClient,
)
from app.config import Settings


def _settings(app_id: str = "wx-app-id", app_secret: str = "wx-secret") -> Settings:
    return Settings.model_validate({"wechat": {"app_id": app_id, "app_secret": app_secret}})


def _client(handler, settings: Settings | None = None) -> WechatMiniClient:
    return WechatMiniClient(
        settings=settings or _settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _json(payload: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return handler


# ---------- 是否配置 ----------


def test_configured_false_without_credentials():
    client = WechatMiniClient(settings=_settings("", ""))
    assert client.configured is False


def test_configured_true_with_credentials():
    assert WechatMiniClient(settings=_settings()).configured is True


async def test_unconfigured_raises_readable_error():
    client = WechatMiniClient(settings=_settings("", ""))
    with pytest.raises(WechatAuthError, match="微信小程序未配置"):
        await client.code2session("code-1")


async def test_empty_code_raises():
    with pytest.raises(WechatAuthError, match="缺少微信登录 code"):
        await _client(_json({})).code2session("")


# ---------- 成功路径 ----------


async def test_code2session_success_returns_openid():
    client = _client(_json({"openid": "openid-abc", "session_key": "sk", "unionid": "un-1"}))
    data = await client.code2session("code-1")
    assert data["openid"] == "openid-abc"
    assert data["session_key"] == "sk"


async def test_login_namespaces_open_id():
    """微信用户写进 wechat: 命名空间, 与飞书的 ou_* 不会撞"""
    client = _client(_json({"openid": "openid-abc", "unionid": "un-1"}))
    identity = await client.login("code-1")
    assert identity["open_id"] == "wechat:openid-abc"
    assert identity["name"] == "微信用户"
    assert identity["union_id"] == "un-1"


async def test_request_carries_appid_and_code():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"openid": "openid-abc"})

    await _client(handler).code2session("code-xyz")
    assert seen["url"].startswith(CODE2SESSION_URL)
    assert "appid=wx-app-id" in seen["url"]
    assert "js_code=code-xyz" in seen["url"]
    assert "grant_type=authorization_code" in seen["url"]


# ---------- 失败路径 ----------


async def test_business_errcode_is_raised():
    """微信用 200 + errcode 表达失败 (40029 = code 无效)"""
    client = _client(_json({"errcode": 40029, "errmsg": "invalid code"}))
    with pytest.raises(WechatAuthError, match="40029"):
        await client.code2session("bad-code")


async def test_http_error_is_raised():
    client = _client(_json({"errmsg": "boom"}, status_code=502))
    with pytest.raises(WechatAuthError, match="HTTP 502"):
        await client.code2session("code-1")


async def test_non_json_body_is_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(WechatAuthError, match="非 JSON"):
        await _client(handler).code2session("code-1")


async def test_missing_openid_is_raised():
    with pytest.raises(WechatAuthError, match="openid"):
        await _client(_json({"session_key": "sk"})).code2session("code-1")


async def test_network_error_becomes_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(WechatAuthError, match="请求失败"):
        await _client(handler).code2session("code-1")


async def test_login_propagates_failure():
    client = _client(_json({"errcode": 40013, "errmsg": "invalid appid"}))
    with pytest.raises(WechatAuthError):
        await client.login("code-1")
