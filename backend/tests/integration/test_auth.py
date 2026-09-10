"""集成测试: 飞书扫码登录、会话续期与多用户隔离"""
from __future__ import annotations

from typing import Any, Dict, List

from app.auth.feishu_oauth import get_feishu_oauth_client
from app.models.user import User
from sqlalchemy import func, select

from tests.conftest import requires_mysql

pytestmark = requires_mysql

ACCESS_COOKIE = "mp_access"
REFRESH_COOKIE = "mp_refresh"


class FakeFeishuClient:
    """替身: 只关心"换到哪个飞书身份", 不发起任何网络请求"""

    def __init__(self, identity: Dict[str, Any]):
        self.identity = dict(identity)
        self.codes: List[str] = []

    def build_authorize_url(self, state: str) -> str:
        return f"https://open.feishu.cn/open-apis/authen/v1/index?state={state}"

    async def login(self, code: str) -> Dict[str, Any]:
        self.codes.append(code)
        return dict(self.identity)


def _set_fake(app, fake: FakeFeishuClient):
    app.dependency_overrides[get_feishu_oauth_client] = lambda: fake


def _clear_fake(app):
    app.dependency_overrides.pop(get_feishu_oauth_client, None)


async def _users(db) -> List[User]:
    await db.rollback()
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


async def _login(api_client, fake: FakeFeishuClient, code: str = "code-1"):
    from app.main import app

    _set_fake(app, fake)
    try:
        return await api_client.get("/api/auth/feishu/callback", params={"code": code})
    finally:
        _clear_fake(app)


async def test_first_login_creates_user_and_sets_cookies(api_client, db_session):
    fake = FakeFeishuClient(
        {"open_id": "ou_alice", "union_id": "un_alice", "name": "小 A", "avatar_url": "https://x/a.png"}
    )
    response = await _login(api_client, fake)

    assert response.status_code == 307
    cookies = "; ".join(response.headers.get_list("set-cookie"))
    assert ACCESS_COOKIE in cookies
    assert REFRESH_COOKIE in cookies
    assert "HttpOnly" in cookies

    users = await _users(db_session)
    assert len(users) == 1
    assert users[0].open_id == "ou_alice"
    assert users[0].name == "小 A"
    assert users[0].last_login_at is not None


async def test_second_login_reuses_same_user(api_client, db_session):
    await _login(api_client, FakeFeishuClient({"open_id": "ou_bob", "name": "小 B"}))
    await _login(
        api_client,
        FakeFeishuClient({"open_id": "ou_bob", "union_id": "un_bob", "name": "小 B 改名"}),
        code="code-2",
    )

    users = await _users(db_session)
    assert len(users) == 1
    assert users[0].name == "小 B 改名"
    assert users[0].union_id == "un_bob"


async def test_login_url_returns_authorize_url(api_client):
    from app.main import app

    _set_fake(app, FakeFeishuClient({"open_id": "unused"}))
    try:
        response = await api_client.get("/api/auth/feishu/login-url")
    finally:
        _clear_fake(app)

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert "authen/v1/index" in payload["data"]["authorize_url"]
    assert payload["data"]["state"]


async def test_me_requires_login(api_client, db_session):
    from tests.factories import make_user

    user = await make_user(db_session, open_id="ou_carol", name="Carol")
    await db_session.commit()

    anonymous = await api_client.get("/api/auth/me")
    assert anonymous.status_code == 401

    from app.main import app

    _set_fake(app, FakeFeishuClient({"open_id": "ou_carol"}))
    try:
        await api_client.get("/api/auth/feishu/callback", params={"code": "c"})
    finally:
        _clear_fake(app)

    authed = await api_client.get("/api/auth/me")
    assert authed.status_code == 200
    assert authed.json()["data"]["id"] == user.id
    assert authed.json()["data"]["open_id"] == "ou_carol"


async def test_refresh_rotates_session(api_client, db_session):
    from tests.factories import make_user

    user = await make_user(db_session, open_id="ou_dave", name="Dave")
    await db_session.commit()

    await _login(api_client, FakeFeishuClient({"open_id": "ou_dave"}), code="d")

    refreshed = await api_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["id"] == user.id

    logged_out = await api_client.post("/api/auth/logout")
    assert logged_out.status_code == 200


async def test_refresh_without_cookie_is_401(api_client, db_session):
    response = await api_client.post("/api/auth/refresh")
    assert response.status_code == 401


async def test_callback_without_code_redirects_with_error(api_client, db_session):
    response = await api_client.get("/api/auth/feishu/callback")
    assert response.status_code == 307
    assert "login_error" in response.headers.get("location", "")


async def test_open_id_is_unique(api_client, db_session):
    await _login(api_client, FakeFeishuClient({"open_id": "ou_eve"}))
    await _login(api_client, FakeFeishuClient({"open_id": "ou_eve"}), code="second")

    count = (await db_session.execute(select(func.count(User.id)))).scalar_one()
    assert count == 1


async def test_dev_login_disabled_by_default(api_client, db_session):
    providers = await api_client.get("/api/auth/providers")
    assert providers.status_code == 200
    assert providers.json()["data"]["dev_login"] is False

    blocked = await api_client.post("/api/auth/dev-login", json={"name": "黑客"})
    assert blocked.status_code == 404


async def test_dev_login_creates_user_and_sets_cookies(api_client, db_session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().auth, "dev_login", True)

    providers = await api_client.get("/api/auth/providers")
    assert providers.json()["data"]["dev_login"] is True

    response = await api_client.post("/api/auth/dev-login", json={"name": "本地小明"})
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "本地小明"
    cookies = "; ".join(response.headers.get_list("set-cookie"))
    assert ACCESS_COOKIE in cookies

    me = await api_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["open_id"] == "dev:本地小明"

    users = await _users(db_session)
    assert [user.open_id for user in users] == ["dev:本地小明"]


async def test_dev_login_same_name_reuses_user(api_client, db_session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().auth, "dev_login", True)

    await api_client.post("/api/auth/dev-login", json={"name": "甲"})
    await api_client.post("/api/auth/dev-login", json={"name": "乙"})
    await api_client.post("/api/auth/dev-login", json={"name": "甲"})

    users = await _users(db_session)
    assert len(users) == 2
    assert {user.open_id for user in users} == {"dev:甲", "dev:乙"}


async def test_dev_login_requires_name(api_client, db_session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().auth, "dev_login", True)
    response = await api_client.post("/api/auth/dev-login", json={"name": ""})
    assert response.status_code == 422
