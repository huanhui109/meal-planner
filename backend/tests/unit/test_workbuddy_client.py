from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest
from app.config import Settings, WorkBuddySettings
from app.services.workbuddy_client import SCOPES, WorkBuddyClient, WorkBuddyError
from app.services.workbuddy_service import WorkBuddyService


def settings() -> Settings:
    return Settings(
        workbuddy=WorkBuddySettings(
            client_id="test-app", client_secret="test-secret",
            redirect_uri="http://127.0.0.1:5173/api/assistant/workbuddy/callback",
        ),
        auth={"jwt_secret": "test-encryption-secret-that-is-at-least-32-characters"},
    )


def test_configuration_and_authorization_use_only_required_scopes():
    client = WorkBuddyClient(settings())
    assert client.configured
    query = parse_qs(httpx.URL(client.authorize_url("state")).query.decode())
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert query["state"] == ["state"]
    assert "test-secret" not in client.authorize_url("state")
    for uri in ("http://remote.example/callback", "https://user:pass@example.com", "javascript:alert(1)"):
        client.settings.workbuddy.redirect_uri = uri
        assert not client.configured


async def test_documented_oauth_and_local_assistant_protocol():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/token"):
            form = parse_qs(request.content.decode())
            assert form["client_secret"] == ["test-secret"]
            assert form["grant_type"] == ["authorization_code"]
            return httpx.Response(200, json={
                "access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
                "scope": " ".join(SCOPES),
            })
        assert request.headers["authorization"] == "Bearer access"
        if request.url.path.endswith("/localassistant"):
            return httpx.Response(200, json={"code": 0, "data": {"online": True}})
        if request.method == "POST":
            assert json.loads(request.content) == {"content": "要求", "msg_type": "text"}
            return httpx.Response(200, json={"code": 0, "data": {"message_id": "msg-1"}})
        assert request.url.params["message_id"] == "msg-1"
        return httpx.Response(200, json={"code": 0, "data": {"messages": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        client = WorkBuddyClient(settings(), transport)
        assert (await client.token(code="code"))["access_token"] == "access"
        assert await client.online("access")
        assert await client.send("access", "要求") == "msg-1"
        assert await client.messages("access", "msg-1") == []
    assert len(requests) == 4


@pytest.mark.parametrize(("status", "body", "reauthorize", "transient"), [
    (401, {"error": "secret-from-upstream"}, True, False),
    (403, {}, True, False),
    (400, {"error": "invalid_grant"}, True, False),
    (429, {}, False, True),
    (503, {}, False, True),
    (302, {}, False, False),
    (200, {"code": 1, "msg": "secret-from-upstream"}, False, False),
])
async def test_errors_are_bounded_redacted_and_do_not_follow_redirects(status, body, reauthorize, transient):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body, headers={"Location": "https://untrusted.example"}),
    )) as transport:
        client = WorkBuddyClient(settings(), transport)
        with pytest.raises(WorkBuddyError) as error:
            await client.online("access")
        assert error.value.reauthorize == reauthorize
        assert error.value.transient == transient
        assert "secret-from-upstream" not in str(error.value)


async def test_network_timeout_and_invalid_scope_are_not_success():
    def timeout(request):
        raise httpx.ReadTimeout("contains-access-token", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as transport:
        with pytest.raises(WorkBuddyError) as error:
            await WorkBuddyClient(settings(), transport).send("access", "要求")
        assert error.value.transient
        assert "contains-access-token" not in str(error.value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "access_token": "access", "expires_in": 3600, "scope": "user.profile.readable",
    }))) as transport:
        with pytest.raises(WorkBuddyError, match="调用权限"):
            await WorkBuddyClient(settings(), transport).token(code="code")


def test_credentials_are_authenticated_encrypted_and_key_scoped():
    service = WorkBuddyService(None, WorkBuddyClient(settings()))
    encrypted = service.cipher().encrypt(b"access-token").decode()
    assert "access-token" not in encrypted
    assert service.cipher().decrypt(encrypted.encode()) == b"access-token"
    service.client.settings.workbuddy.encryption_key = "other-encryption-key-of-at-least-32-characters"
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        service.cipher().decrypt(encrypted.encode())
