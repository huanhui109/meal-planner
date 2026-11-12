"""Unit tests for the sign-in flow and the model catalog/selection.

The sign-in protocol is copied from dsh-connect-workbuddy v5.21.3
(``src/oauth.ts``): auth/state -> user opens authUrl -> poll auth/token ->
login/account -> write the plugin's vault document. These tests pin the three
security rules that make it safe to ship: a session is region-bound, it expires,
and a token never appears in an error/poll message.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from app.config import Settings, WorkBuddySettings
from app.services import workbuddy_login_service as login_mod
from app.services.workbuddy_login_service import (
    WorkBuddyLoginService,
    billing_base,
)
from app.services.workbuddy_model_catalog import ModelCatalogService
from app.services.workbuddy_model_client import WorkBuddyModelClient

TOKEN = "private-access-token-for-tests"


def _settings(vault: Path, **over) -> Settings:
    return Settings(workbuddy=WorkBuddySettings(vault_dir=str(vault), **over))


class FakeHttp:
    """Canned upstream responses keyed by path fragment."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        for fragment, payload in self.routes.items():
            if fragment in url:
                return _Response(payload)
        return _Response({"code": 404, "msg": "no route"}, status=404)


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "workbuddy-vault"


def _catalog_file(tmp_path: Path) -> Path:
    path = tmp_path / ".workbuddy-catalog.json"
    path.write_text(json.dumps({"version": 1, "entries": {"k:": {"models": [
        {"id": "hy4free", "name": "Hy4", "billing": {"free": True, "credits": "x0.00 credits"}},
        {"id": "kimi-k3-1", "name": "Kimi-K3", "billing": {"free": False, "credits": "x1.62 credits"}},
    ]}}}), encoding="utf-8")
    return path


# ---------------------------------------------------------------- sign-in

def test_billing_base_is_single_homed_for_cn():
    assert billing_base("cn") == login_mod.CN_BILLING_BASE
    assert billing_base("global") == login_mod.GLOBAL_CHAT_BASE
    assert billing_base("global", "https://www.codebuddy.ai/") == "https://www.codebuddy.ai"


async def test_start_returns_a_url_and_never_leaks_a_token(vault: Path):
    http = FakeHttp({"/auth/state": {"code": 0, "data": {"state": "st-1", "authUrl": "https://x/login?state=st-1"}}})
    service = WorkBuddyLoginService(_settings(vault), client=http)
    result = await service.start("cn")
    assert result["ok"] is True and "login_id" in result
    assert result["verification_uri"] == "https://x/login?state=st-1"
    assert TOKEN not in json.dumps(result)


async def test_start_falls_back_to_a_login_url_when_upstream_omits_one(vault: Path):
    http = FakeHttp({"/auth/state": {"code": 0, "data": {"state": "st-9"}}})
    result = await WorkBuddyLoginService(_settings(vault), client=http).start("cn")
    assert result["verification_uri"].endswith("/login?state=st-9")


async def test_start_reports_an_unreachable_upstream_without_raising(vault: Path):
    http = FakeHttp({})  # every route 404s
    result = await WorkBuddyLoginService(_settings(vault), client=http).start("cn")
    assert result["ok"] is False and "无法连接" in result["error"]


async def test_poll_waits_then_writes_the_vault_document(vault: Path, tmp_path: Path):
    routes = {
        "/auth/state": {"code": 0, "data": {"state": "st-1", "authUrl": "https://x/a"}},
        "/auth/token": {"code": 0, "data": {
            "accessToken": TOKEN, "refreshToken": "private-refresh",
            "expiresIn": 3600, "domain": "www.workbuddy.cn",
        }},
        "/login/account": {"code": 0, "data": {"uid": "u-1", "nickname": "七号公路"}},
    }
    http = FakeHttp(routes)
    service = WorkBuddyLoginService(_settings(vault), client=http)
    started = await service.start("cn")
    polled = await service.poll(started["login_id"], "cn")
    assert polled["done"] is True and polled["nickname"] == "七号公路"

    written = list((vault / "cn").glob("*.json"))
    assert len(written) == 1
    document = json.loads(written[0].read_text())
    assert document["auth"]["accessToken"] == TOKEN
    assert document["auth"]["domain"] == "www.workbuddy.cn"
    assert document["account"]["nickname"] == "七号公路"
    assert oct(written[0].stat().st_mode)[-3:] == "600"

    # The written vault is immediately discoverable by the chat client.
    client = WorkBuddyModelClient(_settings(vault))
    cred = await client.resolve()
    assert cred is not None and cred["access_token"] == TOKEN and cred["region"] == "cn"


async def test_poll_without_a_token_stays_pending_and_writes_nothing(vault: Path):
    http = FakeHttp({
        "/auth/state": {"code": 0, "data": {"state": "st-1"}},
        "/auth/token": {"code": 1001, "msg": "waiting"},
    })
    service = WorkBuddyLoginService(_settings(vault), client=http)
    started = await service.start("cn")
    polled = await service.poll(started["login_id"], "cn")
    assert polled["ok"] is True and polled["done"] is False
    assert not list(vault.glob("*/*.json"))


async def test_session_is_bound_to_its_region(vault: Path):
    http = FakeHttp({"/auth/state": {"code": 0, "data": {"state": "st-1"}}})
    service = WorkBuddyLoginService(_settings(vault), client=http)
    started = await service.start("cn")
    rejected = await service.poll(started["login_id"], "global")
    assert rejected["done"] is True and "另一个版本" in rejected["error"]
    # The binding check runs BEFORE any I/O: only the start call was made.
    assert len(http.calls) == 1


async def test_unknown_session_and_expiry_are_terminal(vault: Path):
    service = WorkBuddyLoginService(_settings(vault), client=FakeHttp({}))
    assert (await service.poll("wbo_missing"))["done"] is True
    http = FakeHttp({"/auth/state": {"code": 0, "data": {"state": "st"}}})
    service = WorkBuddyLoginService(_settings(vault), client=http)
    started = await service.start("cn")
    service._sessions[started["login_id"]].expires_at = time.time() - 1
    expired = await service.poll(started["login_id"])
    assert expired["done"] is True and "超时" in expired["error"]


async def test_logout_removes_only_the_named_region(vault: Path, tmp_path: Path):
    for region in ("cn", "global"):
        (vault / region).mkdir(parents=True)
        (vault / region / "a.json").write_text("{}", encoding="utf-8")
    result = await WorkBuddyLoginService(_settings(vault), client=FakeHttp({})).logout("cn")
    assert result["removed"] == 1
    assert list((vault / "cn").glob("*.json")) == []
    assert len(list((vault / "global").glob("*.json"))) == 1


# ---------------------------------------------------------------- catalog

class _FakeDb:
    def __init__(self):
        self.added = []
        self.rows = []

    def add(self, row):
        self.added.append(row)
        self.rows.append(row)

    async def commit(self):
        return None

    async def execute(self, _statement):
        class _Result:
            def __init__(self, row):
                self._row = row

            def scalar_one_or_none(self):
                return self._row

        return _Result(self.rows[-1] if self.rows else None)


async def test_catalog_lists_models_with_credits_and_free_flag(tmp_path: Path):
    client = WorkBuddyModelClient(Settings(workbuddy=WorkBuddySettings(
        vault_dir=str(tmp_path / "v"), catalog_file=str(_catalog_file(tmp_path)),
    )))
    service = ModelCatalogService(_FakeDb(), client)
    listed = service.catalog()
    assert [item["id"] for item in listed] == ["hy4free", "kimi-k3-1"]
    assert listed[0]["free"] is True and listed[0]["credits"] == "x0.00 credits"
    assert listed[1]["free"] is False and listed[1]["credits"] == "x1.62 credits"


async def test_effective_model_prefers_selection_then_free(tmp_path: Path):
    client = WorkBuddyModelClient(Settings(workbuddy=WorkBuddySettings(
        vault_dir=str(tmp_path / "v"), catalog_file=str(_catalog_file(tmp_path)),
    )))
    service = ModelCatalogService(_FakeDb(), client)
    catalog = service.catalog()
    assert service.effective_model(catalog, {"model": ""}) == "hy4free"
    assert service.effective_model(catalog, {"model": "kimi-k3-1"}) == "kimi-k3-1"


async def test_choose_rejects_a_model_outside_the_catalog(tmp_path: Path):
    client = WorkBuddyModelClient(Settings(workbuddy=WorkBuddySettings(
        vault_dir=str(tmp_path / "v"), catalog_file=str(_catalog_file(tmp_path)),
    )))
    service = ModelCatalogService(_FakeDb(), client)
    with pytest.raises(ValueError, match="不在本机"):
        await service.choose(1, "not-a-real-model")
    with pytest.raises(ValueError, match="区域"):
        await service.choose(1, "hy4free", "mars")


async def test_choose_persists_an_empty_selection_as_auto(tmp_path: Path):
    db = _FakeDb()
    client = WorkBuddyModelClient(Settings(workbuddy=WorkBuddySettings(
        vault_dir=str(tmp_path / "v"), catalog_file=str(_catalog_file(tmp_path)),
    )))
    service = ModelCatalogService(db, client)
    await service.choose(1, "", "")
    assert json.loads(db.added[-1].detail) == {"model": "", "region": ""}
    assert db.added[-1].kind == "model_preference"


async def test_login_session_survives_across_requests(vault: Path):
    """Regression: FastAPI resolves the dependency factory per request.

    A login started by `POST /login` must be pollable by the NEXT request, which
    gets a fresh service object. This used to fail with "登录会话不存在" because
    the session map was instance-level.
    """
    from app.services.workbuddy_login_service import get_workbuddy_login_service

    http = FakeHttp({"/auth/state": {"code": 0, "data": {"state": "st-1", "authUrl": "https://x/a"}}})
    started = await WorkBuddyLoginService(_settings(vault), client=http).start("cn")

    # A brand-new instance, exactly as Depends() would build it next request.
    next_request = get_workbuddy_login_service()
    polled = await next_request.poll(started["login_id"], "cn")
    assert polled.get("error") != "登录会话不存在，请重新发起登录"
    assert polled["ok"] is True and polled["done"] is False


async def test_logout_then_new_login_starts_a_fresh_session(vault: Path, tmp_path: Path):
    """退出登录后重新发起必须能拿到全新会话，而不是复用/丢失旧 id。"""
    routes = {
        "/auth/state": {"code": 0, "data": {"state": "st-1", "authUrl": "https://x/a"}},
        "/auth/token": {"code": 0, "data": {
            "accessToken": TOKEN, "refreshToken": "private-refresh", "expiresIn": 3600,
            "domain": "www.workbuddy.cn",
        }},
        "/login/account": {"code": 0, "data": {"uid": "u-1", "nickname": "七号公路"}},
    }
    service = WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes))
    first = await service.start("cn")
    assert (await service.poll(first["login_id"], "cn"))["done"] is True
    assert len(list((vault / "cn").glob("*.json"))) == 1

    await service.logout("cn")
    assert list((vault / "cn").glob("*.json")) == []

    # Re-sign-in uses a NEW session id and must NOT be confused with the old one.
    second = await WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes)).start("cn")
    assert second["login_id"] != first["login_id"]
    # The pre-logout session id must be dead: no zombie poll can resurrect it.
    zombie = await WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes)).poll(
        first["login_id"], "cn",
    )
    assert zombie["done"] is True and zombie.get("error")
    again = await WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes)).poll(
        second["login_id"], "cn",
    )
    assert again["ok"] is True and again["done"] is True
    assert len(list((vault / "cn").glob("*.json"))) == 1


async def test_duplicate_poll_after_success_is_an_idempotent_success(vault: Path):
    """A completed sign-in must never answer "session not found" to a retry."""
    routes = {
        "/auth/state": {"code": 0, "data": {"state": "st-1", "authUrl": "https://x/a"}},
        "/auth/token": {"code": 0, "data": {
            "accessToken": TOKEN, "refreshToken": "private-refresh", "expiresIn": 3600,
            "domain": "www.workbuddy.cn",
        }},
        "/login/account": {"code": 0, "data": {"uid": "u-1", "nickname": "七号公路"}},
    }
    service = WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes))
    started = await service.start("cn")
    first = await service.poll(started["login_id"], "cn")
    assert first["done"] is True and first["nickname"] == "七号公路"
    # A different instance (next request) polls the same id again.
    duplicate = await WorkBuddyLoginService(_settings(vault), client=FakeHttp(routes)).poll(
        started["login_id"], "cn",
    )
    assert duplicate["ok"] is True and duplicate["done"] is True
    assert duplicate["nickname"] == "七号公路"
    assert "session" not in json.dumps(duplicate).lower()
