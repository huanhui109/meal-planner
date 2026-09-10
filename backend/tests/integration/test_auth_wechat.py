"""集成测试: 微信小程序一键登录

微信用户沿用 `open_id` 字段, 用 `wechat:` 前缀与飞书的 `ou_*` / 本地开发的 `dev:`
分命名空间, 所以本期不需要新的数据表列或迁移。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.auth.wechat_oauth import WechatAuthError, get_wechat_mini_client
from app.models.user import User
from sqlalchemy import func, select

from tests.conftest import requires_mysql

pytestmark = requires_mysql


class FakeWechatClient:
    """替身: 只关心"换到哪个 openid", 不发起任何网络请求"""

    configured = True

    def __init__(self, openid: str = "openid-alice"):
        self.openid = openid
        self.codes: List[str] = []

    async def code2session(self, code: str) -> Dict[str, Any]:
        self.codes.append(code)
        return {"openid": self.openid, "session_key": "sk"}

    async def login(self, code: str) -> Dict[str, Any]:
        data = await self.code2session(code)
        return {
            "open_id": f"wechat:{data['openid']}",
            "union_id": None,
            "name": "微信用户",
            "avatar_url": None,
        }


class BrokenWechatClient:
    configured = True

    async def login(self, code: str) -> Dict[str, Any]:
        raise WechatAuthError("微信登录失败(40029): invalid code")


class UnconfiguredWechatClient:
    """没配 AppID/Secret 时的真实客户端形态"""

    configured = False

    async def login(self, code: str) -> Dict[str, Any]:
        raise AssertionError("未配置时不应该走到网络请求")


def _set_fake(app, fake: Any):
    app.dependency_overrides[get_wechat_mini_client] = lambda: fake


def _clear_fake(app):
    app.dependency_overrides.pop(get_wechat_mini_client, None)


async def _users(db) -> List[User]:
    await db.rollback()
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


async def _mini_login(api_client, fake: Any, code: str = "code-1"):
    from app.main import app

    _set_fake(app, fake)
    try:
        return await api_client.post("/api/auth/wechat/mini-login", json={"code": code})
    finally:
        _clear_fake(app)


async def test_first_login_creates_user_and_returns_tokens(api_client, db_session):
    response = await _mini_login(api_client, FakeWechatClient("openid-alice"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0
    assert data["user"]["open_id"] == "wechat:openid-alice"
    assert data["user"]["name"] == "微信用户"

    # 小程序走 Bearer, 不依赖 Cookie
    assert "set-cookie" not in {key.lower() for key in response.headers.keys()}

    users = await _users(db_session)
    assert len(users) == 1
    assert users[0].open_id == "wechat:openid-alice"
    assert users[0].last_login_at is not None


async def test_second_login_reuses_same_user(api_client, db_session):
    await _mini_login(api_client, FakeWechatClient("openid-bob"))
    await _mini_login(api_client, FakeWechatClient("openid-bob"), code="code-2")
    await _mini_login(api_client, FakeWechatClient("openid-bob"), code="code-3")

    count = (await db_session.execute(select(func.count(User.id)))).scalar_one()
    assert count == 1


async def test_issued_access_token_works_on_me(api_client, db_session):
    response = await _mini_login(api_client, FakeWechatClient("openid-carol"))
    token = response.json()["data"]["access_token"]

    me = await api_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["open_id"] == "wechat:openid-carol"


async def test_providers_exposes_wechat(api_client, db_session):
    from app.main import app

    _set_fake(app, FakeWechatClient())
    try:
        providers = await api_client.get("/api/auth/providers")
    finally:
        _clear_fake(app)

    assert providers.status_code == 200
    assert providers.json()["data"]["wechat"] is True


async def test_providers_hides_wechat_when_not_configured(api_client, db_session):
    """没有 AppID/Secret 时, 登录页不应该显示微信入口"""
    providers = await api_client.get("/api/auth/providers")
    assert providers.json()["data"]["wechat"] is False


async def test_refresh_via_body_rotates_tokens(api_client, db_session):
    login = await _mini_login(api_client, FakeWechatClient("openid-dave"))
    tokens = login.json()["data"]

    refreshed = await api_client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    data = refreshed.json()["data"]
    # 响应体里直接给新令牌 (小程序没有可靠 cookie jar)
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["open_id"] == "wechat:openid-dave"

    me = await api_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["data"]["open_id"] == "wechat:openid-dave"


async def test_refresh_with_access_token_in_body_is_rejected(api_client, db_session):
    """只有 refresh 类型的令牌能续期, 拿 access_token 来换必须失败"""
    login = await _mini_login(api_client, FakeWechatClient("openid-erin"))
    access = login.json()["data"]["access_token"]

    refreshed = await api_client.post("/api/auth/refresh", json={"refresh_token": access})
    assert refreshed.status_code == 401


async def test_refresh_with_garbage_body_token_is_401(api_client, db_session):
    refreshed = await api_client.post("/api/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert refreshed.status_code == 401


async def test_unconfigured_wechat_is_503_not_401(api_client, db_session):
    """服务端没配微信, 不能报 401 让用户以为是自己 code 错了"""
    response = await _mini_login(api_client, UnconfiguredWechatClient())

    assert response.status_code == 503
    assert "APP__WECHAT__APP_ID" in response.json()["detail"]


async def test_wechat_login_failure_is_readable_401(api_client, db_session):
    response = await _mini_login(api_client, BrokenWechatClient())
    assert response.status_code == 401
    assert "40029" in response.json()["detail"]

    count = (await db_session.execute(select(func.count(User.id)))).scalar_one()
    assert count == 0


async def test_wechat_and_feishu_users_are_isolated(api_client, db_session):
    """微信账号与飞书账号并存: 两个独立用户, 数据互不可见"""
    from tests.factories import make_preferences

    wechat = (await _mini_login(api_client, FakeWechatClient("openid-frank"))).json()["data"]
    await db_session.commit()

    from tests.factories import make_user

    feishu_user = await make_user(db_session, open_id="ou_frank", name="飞书 Frank")
    await make_preferences(db_session, feishu_user.id, weekly_cap=999.0)
    await db_session.commit()

    users = await _users(db_session)
    assert {user.open_id for user in users} == {"wechat:openid-frank", "ou_frank"}

    # 各带各的令牌访问 /preferences/summary, 只看到自己那份
    wechat_headers = {"Authorization": f"Bearer {wechat['access_token']}"}
    wechat_summary = await api_client.get("/api/preferences/summary", headers=wechat_headers)
    assert wechat_summary.status_code == 200
    assert wechat_summary.json()["data"]["budget"] is None

    feishu_headers = await _async_headers(db_session, feishu_user.id)
    feishu_summary = await api_client.get("/api/preferences/summary", headers=feishu_headers)
    assert feishu_summary.status_code == 200
    assert feishu_summary.json()["data"]["budget"]["weekly_cap"] == 999.0


async def _async_headers(db, user_id: int) -> Dict[str, str]:
    from app.auth.tokens import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user_id)}"}
