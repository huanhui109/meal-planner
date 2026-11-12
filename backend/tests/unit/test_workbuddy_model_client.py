"""Unit tests for the unified direct-model client (no MySQL, no network).

These pin the contract copied from dsh-connect-workbuddy v5.21.3:
  * vault/catalog artifacts are READ-ONLY and parsed by region/domain;
  * a checked envelope is returned (`ok` FIRST, then text) — the plugin's own
    issue #56 warning says skipping this reports failures as successes;
  * SSE is consumed to `data: [DONE]`, `reasoning_content` is NOT the answer;
  * chat headers are CLI-shaped, carry NO refresh token, and are fresh per call;
  * business codes are classified to honest Chinese, token-free messages;
  * the free model is chosen from the plugin's catalog.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from app.config import Settings, WorkBuddySettings
from app.services import workbuddy_model_client as mod
from app.services.workbuddy_model_client import WorkBuddyModelClient


def _settings(**over) -> Settings:
    return Settings(workbuddy=WorkBuddySettings(**over))


@pytest.fixture
def vault(tmp_path: Path):
    """A fake dsh-connect-workbuddy vault + catalog, no real credentials."""
    root = tmp_path / "dsh"
    (root / "workbuddy-vault" / "cn").mkdir(parents=True)
    (root / "workbuddy-vault" / "global").mkdir(parents=True)
    cn = {
        "version": 2, "accountId": "cn-account",
        "auth": {
            "accessToken": "private-cn-access-token", "refreshToken": "private-cn-refresh-token",
            "expiresAt": int(time.time()) + 3600, "domain": "www.workbuddy.cn",
        },
        "account": {"uid": "u1", "nickname": "tester"},
    }
    gl = {
        "version": 2, "accountId": "global-account",
        "auth": {
            "accessToken": "private-global-access-token", "refreshToken": "private-global-refresh-token",
            "expiresAt": int(time.time()) + 7200, "domain": "www.workbuddy.ai",
        },
        "account": {"uid": "u2", "nickname": "tester-intl"},
    }
    (root / "workbuddy-vault" / "cn" / "cn-account.json").write_text(json.dumps(cn), encoding="utf-8")
    (root / "workbuddy-vault" / "global" / "global-account.json").write_text(json.dumps(gl), encoding="utf-8")
    catalog = {
        "version": 1,
        "entries": {
            "key:": {"models": [
                {"id": "hy4free", "name": "Hy4", "billing": {"free": True}},
                {"id": "kimi-k3-1", "name": "Kimi", "billing": {"free": False}},
            ]},
        },
    }
    (root / ".workbuddy-catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return root


def _client(vault: Path, **over) -> WorkBuddyModelClient:
    return WorkBuddyModelClient(_settings(
        vault_dir=str(vault / "workbuddy-vault"),
        catalog_file=str(vault / ".workbuddy-catalog.json"), **over,
    ))


# ---------------------------------------------------------------- vault / catalog

def test_reads_vault_readonly_and_selects_cn_by_default(vault: Path):
    client = _client(vault)
    cred = asyncio.run(client.resolve())
    assert cred is not None
    assert cred["region"] == "cn"
    assert cred["access_token"] == "private-cn-access-token"
    assert cred["account_id"] == "cn-account"
    # The token file must not be modified by resolve()/status().
    before = (vault / "workbuddy-vault" / "cn" / "cn-account.json").read_bytes()
    asyncio.run(client.status())
    after = (vault / "workbuddy-vault" / "cn" / "cn-account.json").read_bytes()
    assert before == after


def test_status_is_readonly_and_truthful_when_vault_missing(tmp_path: Path):
    client = WorkBuddyModelClient(_settings(
        vault_dir=str(tmp_path / "missing-vault"), catalog_file=str(tmp_path / "missing.json"),
    ))
    status = asyncio.run(client.status())
    assert status["available"] is False
    assert "登录态不可用" in status["message"]
    for secret in ("private-", "fd_skill_", "fd_ib_"):
        assert secret not in status["message"]


def test_region_routing_and_free_model_choice(vault: Path):
    client = _client(vault)
    assert client._region_of("www.workbuddy.ai") == "global"
    assert client._region_of("codebuddy.ai") == "global"
    assert client._region_of("www.workbuddy.cn") == "cn"
    assert client.chat_base("cn") == mod.CN_CHAT_BASE
    assert client.chat_base("global") == mod.GLOBAL_CHAT_BASE
    assert client.choose_model() == "hy4free"
    explicit = _client(vault, model="glm-5.3")
    assert explicit.choose_model() == "glm-5.3"


def test_malformed_vault_is_ignored(vault: Path):
    (vault / "workbuddy-vault" / "cn" / "broken.json").write_text("not json", encoding="utf-8")
    client = _client(vault)
    assert len(client._candidates()) == 2  # the two good files survive


# ---------------------------------------------------------------- headers

def test_chat_headers_are_cli_shaped_and_never_carry_refresh_token(vault: Path):
    client = _client(vault)
    cred = asyncio.run(client.resolve())
    headers = client._headers(cred)
    assert headers["Authorization"] == "Bearer private-cn-access-token"
    assert "X-Refresh-Token" not in headers
    assert headers["User-Agent"] == mod.CLIENT_UA
    assert headers["X-IDE-Name"] == "WorkBuddy" and headers["X-Product"] == "WorkBuddy"
    assert headers["X-Conversation-ID"]
    assert headers["X-Conversation-Request-ID"] == headers["X-Root-Request-ID"]
    assert headers["X-Conversation-Message-ID"]
    second = client._headers(cred)
    assert second["X-Conversation-ID"] != headers["X-Conversation-ID"]  # fresh per request


# ---------------------------------------------------------------- SSE envelope rule

class _FakeResponse:
    def __init__(self, status: int, lines: list[str], payload: dict | None = None):
        self.status_code = status
        self._lines = lines
        self._payload = payload

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeStream:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class _FakeHttp:
    """Minimal injected transport: records the request, replays canned SSE."""

    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def stream(self, method, url, *, content, headers, timeout=None):
        self.calls.append({"method": method, "url": url, "content": content,
                           "headers": headers, "timeout": timeout})
        return _FakeStream(self.response)


def _sse(*texts: str, done: bool = True) -> list[str]:
    lines = []
    for text in texts:
        lines.append("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}))
        lines.append("")
    # A thinking frame must be ignored (it is not the answer channel).
    lines.append("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "internal notes"}}]}))
    lines.append("")
    if done:
        lines.append("data: [DONE]")
        lines.append("")
    return lines


def test_chat_returns_checked_success_envelope(vault: Path):
    client = _client(vault)
    http = _FakeHttp(_FakeResponse(200, _sse('{"request_id":"x","phase":"proposal"}')))
    client._client = http
    envelope = asyncio.run(client.chat("prompt"))
    assert envelope.ok is True
    assert envelope.text == '{"request_id":"x","phase":"proposal"}'
    assert "internal notes" not in (envelope.text or "")
    assert envelope.model == "hy4free" and envelope.region == "cn"
    body = json.loads(http.calls[0]["content"])
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "prompt"
    assert "X-Refresh-Token" not in http.calls[0]["headers"]
    assert http.calls[0]["url"] == f"{mod.CN_CHAT_BASE}{mod.CHAT_PATH}"


def test_failure_is_reported_as_failure_not_consumed_as_success(vault: Path):
    """The chatStream() envelope rule: inspect `ok` before reading text."""
    client = _client(vault)
    http = _FakeHttp(_FakeResponse(429, [], {"code": 6004, "msg": "rate limited"}))
    client._client = http
    envelope = asyncio.run(client.chat("prompt"))
    assert envelope.ok is False
    assert envelope.text is None
    assert envelope.kind == "soft_rate"
    assert "限流" in envelope.message


@pytest.mark.parametrize("code,expected_kind", [
    (14003, "model_busy"), (11128, "channel_reject"), (11140, "policy_reject"),
    (11115, "context_too_long"), (14018, "hard_credit"), (6020, "model_queue"), (6004, "soft_rate"),
])
def test_business_error_frame_inside_sse_is_classified(vault: Path, code, expected_kind):
    client = _client(vault)
    lines = ["data: " + json.dumps({"code": code, "msg": "upstream error"}), "", "data: [DONE]", ""]
    http = _FakeHttp(_FakeResponse(200, lines))
    client._client = http
    envelope = asyncio.run(client.chat("prompt"))
    assert envelope.ok is False
    assert envelope.kind == expected_kind
    assert envelope.message
    assert "upstream error" not in envelope.message  # never echo raw upstream text


def test_no_done_and_empty_stream_is_an_explicit_failure(vault: Path):
    async def scenario():
        client = _client(vault)
        client._client = _FakeHttp(_FakeResponse(200, _sse("partial reply", done=False)))
        assert (await client.chat("prompt")).ok is True  # content already arrived
        client._client = _FakeHttp(_FakeResponse(200, []))
        return await client.chat("prompt")

    envelope = asyncio.run(scenario())
    assert envelope.ok is False and "未返回可用" in envelope.message


def test_no_token_ever_leaks_into_failure_message(vault: Path):
    client = _client(vault)
    client._client = _FakeHttp(_FakeResponse(401, [], {"code": 11140, "msg": "denied"}))
    envelope = asyncio.run(client.chat("prompt"))
    assert envelope.ok is False
    assert "private-" not in envelope.message and "access" not in envelope.message.lower()


def test_refresh_is_single_flight_and_writes_only_memory(vault: Path, monkeypatch):
    client = _client(vault)
    refreshed = {
        "code": 0,
        "data": {"accessToken": "private-refreshed-token", "refreshToken": "private-new-refresh",
                 "expiresIn": 3600, "domain": "www.workbuddy.cn"},
    }

    class _RefreshHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, *, content, headers, timeout=None):
            self.calls += 1
            assert "X-Refresh-Token" in headers
            return _FakeResponse(200, [], refreshed)

        # WorkBuddyModelClient._refresh uses an injected client's post(); chat()
        # would use stream(), so keep this fake out of the chat code path.
        def stream(self, *args, **kwargs):
            raise AssertionError("refresh must not use stream()")

    # Force the single CN credential to be near expiry.
    cred = client._candidates()[0]
    cred["expires_at"] = time.time() + 60
    client._candidates = lambda: [cred]
    http = _RefreshHttp()
    client._client = http

    async def resolve_four():
        return await asyncio.gather(*[client.resolve() for _ in range(4)])

    result = asyncio.run(resolve_four())
    assert all(r is not None and r["access_token"] == "private-refreshed-token" for r in result)
    assert http.calls == 1  # single-flight
    # Vault file on disk is untouched.
    disk = json.loads((vault / "workbuddy-vault" / "cn" / "cn-account.json").read_text())
    assert disk["auth"]["accessToken"] == "private-cn-access-token"


def test_upstream_timeout_degrades_to_an_honest_failure(vault: Path):
    """A timeout must never look like success, and must say it will not resend."""
    import httpx as _httpx

    class _Slow:
        def stream(self, *args, **kwargs):
            raise _httpx.ReadTimeout("timed out")

    async def scenario():
        client = _client(vault)
        client._client = _Slow()
        return await client.chat("prompt")

    envelope = asyncio.run(scenario())
    assert envelope.ok is False
    assert envelope.kind == "server" and envelope.status == 504
    assert "超时" in envelope.message and "不会自动重发" in envelope.message
    assert envelope.text is None


# ---------------------------------------------------------------- low latency + skill routing

def test_chat_applies_low_latency_defaults_and_can_disable_them(vault: Path):
    """Short output + deterministic sampling are ON by default, and switchable."""
    from app.config import WorkBuddySettings

    client = _client(vault)
    http = _FakeHttp(_FakeResponse(200, _sse('{"candidates":[]}')))
    client._client = http
    assert asyncio.run(client.chat("prompt")).ok
    body = json.loads(http.calls[0]["content"])
    defaults = WorkBuddySettings()
    assert body["max_tokens"] == defaults.chat_max_tokens == 1200
    assert body["temperature"] == defaults.chat_temperature == 0.0

    disabled = _client(vault, chat_max_tokens=0, chat_temperature=None)
    http2 = _FakeHttp(_FakeResponse(200, _sse('{"candidates":[]}')))
    disabled._client = http2
    assert asyncio.run(disabled.chat("prompt")).ok
    body2 = json.loads(http2.calls[0]["content"])
    assert "max_tokens" not in body2 and "temperature" not in body2


def test_chat_routes_system_contract_by_skill_prompt(vault: Path):
    """A candidate-generation call must NOT receive the selection-only contract.

    Sending "不得新增候选" to a generation task contradicts its own instruction
    and used to produce empty replies. Routing is by the fixed first prompt line,
    which user text cannot control.
    """
    from app.services import dish_candidate_skill as candidate_skill
    from app.services.fandecide_skill_contract import SYSTEM_CONTRACT

    client = _client(vault)
    http = _FakeHttp(_FakeResponse(200, _sse('{"candidates":[]}')))
    client._client = http
    prompt = candidate_skill.build_prompt("想吃点暖胃的汤")
    assert prompt.startswith(candidate_skill.PROMPT_LEAD)
    assert asyncio.run(client.chat(prompt)).ok
    body = json.loads(http.calls[0]["content"])
    assert body["messages"][0]["content"] == candidate_skill.SYSTEM_CONTRACT
    assert body["messages"][0]["content"] != SYSTEM_CONTRACT

    http2 = _FakeHttp(_FakeResponse(200, _sse('{"request_id":"x"}')))
    client._client = http2
    assert asyncio.run(client.chat("饭决技能任务。只回复一个 JSON 对象。")).ok
    body2 = json.loads(http2.calls[0]["content"])
    assert body2["messages"][0]["content"] == SYSTEM_CONTRACT
