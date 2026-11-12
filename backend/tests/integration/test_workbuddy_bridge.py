"""Unified in-app direct model request — endpoint-level integration (real MySQL).

The old two-phase "web direct" bridge (send prompt into the WorkBuddy
conversation, poll /localassistant/message twice) has been replaced by ONE
direct model call made by the backend during ``GET /adjustments/{id}``. A fake
``WorkBuddyModelClient`` stands in for the locally signed-in upstream; the
legacy official-OAuth ``WorkBuddyClient`` fake is kept because the OAuth
callback/compat endpoints are still exercised here.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from app.config import Settings, WorkBuddySettings
from app.models.allergy_restriction import AllergyRestriction
from app.models.assistant_bridge import AssistantAdjustment, WorkBuddyConnection
from app.models.meal import MealEvent, MealProposal, MealStockMovement
from app.services.meal_service import meal_now
from app.services.workbuddy_client import SCOPES, WorkBuddyClient, get_workbuddy_client
from app.services.workbuddy_model_client import (
    ChatEnvelope,
    WorkBuddyModelClient,
    get_workbuddy_model_client,
)
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql


class FakeWorkBuddyModel(WorkBuddyModelClient):
    """Returns a canned model reply with REAL candidate keys from the prompt."""

    def __init__(self):
        super().__init__(Settings(workbuddy=WorkBuddySettings(model_timeout_seconds=10)))
        self.calls: list[dict] = []
        self.reply_override = None
        self.failure = None
        self.blocking: tuple[asyncio.Event, asyncio.Event] | None = None

    async def status(self):
        return {"available": True, "region": "cn", "model": "hy4free", "message": "本机 WorkBuddy 已登录"}

    async def chat(self, prompt: str, *, model: str = "") -> ChatEnvelope:
        payload = json.loads(prompt.splitlines()[-1])
        self.calls.append(payload)
        if self.blocking:
            entered, resume = self.blocking
            entered.set()
            await asyncio.wait_for(resume.wait(), timeout=5)
        if self.failure is not None:
            return ChatEnvelope.failure(502, "server", self.failure)
        if self.reply_override is not None:
            reply = self.reply_override(payload)
        else:
            candidates = payload.get("candidates") or []
            by_role: dict[str, list[dict]] = {}
            for dish in candidates:
                by_role.setdefault(dish.get("role", ""), []).append(dish)
            servings = (payload.get("context") or {}).get("servings", 1)
            keys: list[str]
            if servings <= 1 and by_role.get("complete"):
                keys = [by_role["complete"][0]["key"]]
            elif by_role.get("main") and by_role.get("side") and by_role.get("staple"):
                keys = [
                    by_role["main"][0]["key"],
                    by_role["side"][0]["key"],
                    by_role["staple"][0]["key"],
                ]
            elif by_role.get("complete") and by_role.get("side"):
                keys = [by_role["complete"][0]["key"], by_role["side"][0]["key"]]
            else:
                keys = [dish["key"] for dish in candidates[:3]]
            reply = {
                "request_id": payload["request_id"], "phase": "proposal",
                "candidate_keys": keys, "reason": "按两人、不开火、不辣的要求搭配",
            }
            # A returned condition patch is re-validated server-side. It must not
            # change the composition family the keys were chosen for.
            reply["context"] = {"mode": "takeout", "max_spice": 0}
        text = json.dumps(reply, ensure_ascii=False)
        return ChatEnvelope.success(text, model="hy4free", region="cn")


class FakeWorkBuddy(WorkBuddyClient):
    """Legacy official-OAuth client; kept for the still-supported OAuth endpoints."""

    def __init__(self):
        super().__init__(Settings(
            workbuddy=WorkBuddySettings(
                client_id="test-app", client_secret="private-client-secret",
                redirect_uri="http://127.0.0.1:5173/api/assistant/workbuddy/callback",
            ),
            auth={"jwt_secret": "test-credential-encryption-key-32-characters"},
        ))
        self.token_calls = []
        self.is_online = True

    async def token(self, **kwargs):
        self.token_calls.append(kwargs)
        return {
            "access_token": "private-access-token", "refresh_token": "private-refresh-token",
            "expires_in": 3600, "scope": " ".join(SCOPES),
        }

    async def online(self, token):
        assert token == "private-access-token"
        return self.is_online


@pytest.fixture
def host():
    from app.main import app

    fake = FakeWorkBuddy()
    model = FakeWorkBuddyModel()
    app.dependency_overrides[get_workbuddy_client] = lambda: fake
    app.dependency_overrides[get_workbuddy_model_client] = lambda: model
    yield model, fake
    app.dependency_overrides.pop(get_workbuddy_client, None)
    app.dependency_overrides.pop(get_workbuddy_model_client, None)


async def connect(api_client, headers):
    response = await api_client.post("/api/assistant/workbuddy/authorize", headers=headers)
    assert response.status_code == 200, response.text
    url = response.json()["data"]["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    response = await api_client.get(
        "/api/assistant/workbuddy/callback", headers=headers, params={"state": state, "code": "test-code"},
    )
    assert response.status_code == 303
    assert "connected" in response.headers["location"]
    return state


async def setup_meal(db_session, api_client, auth_headers, *, connected=True):
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    if connected:
        await connect(api_client, headers)
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    response = await api_client.post("/api/meals/propose", headers=headers, json={
        "context": {**current["context"], "max_minutes": 180, "avoid_recent": False}, "expected_revision": 0,
    })
    assert response.status_code == 200, response.text
    meal = response.json()["data"]
    return user, headers, meal


async def start(api_client, headers, meal, request_id=None):
    body = {
        "request_id": request_id or str(uuid4()), "instruction": "两个人，不开火，不辣",
        "context": meal["context"], "expected_revision": meal["revision"],
    }
    response = await api_client.post("/api/assistant/adjustments", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"], body


async def poll_due(db_session, api_client, headers, job_id):
    job = (await db_session.execute(
        select(AssistantAdjustment).where(AssistantAdjustment.id == job_id)
        .execution_options(populate_existing=True),
    )).scalar_one()
    job.next_poll_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    response = await api_client.get(f"/api/assistant/adjustments/{job_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ------------------------------------------------------------------ status

async def test_model_status_is_readonly_and_lists_the_catalog(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.get("/api/assistant/model", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["available"] is True and data["region"] == "cn"
    # No explicit choice -> auto, resolved from the catalog's free tier.
    assert data["auto"] is True and data["selected"] == ""
    assert data["model"] == "hy4free"
    assert isinstance(data["catalog"], list)
    assert model.calls == []  # status must never call chat


async def test_model_choice_is_user_scoped_and_persisted(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    user = await make_user(db_session)
    other = await make_user(db_session, open_id="other-model-user")
    await db_session.commit()
    headers = auth_headers(user.id)

    rejected = await api_client.post(
        "/api/assistant/model", headers=headers, json={"model": "not-a-real-model"},
    )
    assert rejected.status_code == 422

    chosen = await api_client.post(
        "/api/assistant/model", headers=headers, json={"model": "kimi-k3-1", "region": "cn"},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["data"]["effective"] == "kimi-k3-1"

    mine = (await api_client.get("/api/assistant/model", headers=headers)).json()["data"]
    assert mine["selected"] == "kimi-k3-1" and mine["auto"] is False
    theirs = (await api_client.get(
        "/api/assistant/model", headers=auth_headers(other.id),
    )).json()["data"]
    assert theirs["selected"] == "" and theirs["auto"] is True

    reset = await api_client.post("/api/assistant/model", headers=headers, json={"model": ""})
    assert reset.json()["data"]["auto"] is True


async def test_login_endpoints_are_user_agnostic_but_never_return_tokens(
    api_client,
):
    started = await api_client.post("/api/assistant/login", json={"region": "cn"})
    # An unreachable upstream is reported, not raised; the shape is stable.
    assert started.status_code == 200
    data = started.json()["data"]
    assert "ok" in data
    assert "private-" not in started.text and "fd_skill_" not in started.text
    missing = await api_client.get("/api/assistant/login/wbo_missing")
    assert missing.status_code == 200
    assert missing.json()["data"]["done"] is True


async def test_oauth_state_is_single_use_bound_to_user_and_tokens_stay_encrypted(
    db_session, api_client, auth_headers, host,
):
    _, legacy = host
    user = await make_user(db_session)
    other = await make_user(db_session, open_id="other-workbuddy-user")
    await db_session.commit()
    headers = auth_headers(user.id)
    before = await api_client.get("/api/assistant/workbuddy", headers=headers)
    assert before.json()["data"]["state"] == "disconnected"
    state = await connect(api_client, headers)
    repeated = await api_client.get("/api/assistant/workbuddy/callback", headers=headers, params={
        "state": state, "code": "test-code",
    })
    assert "failed" in repeated.headers["location"]
    crossed = await api_client.get("/api/assistant/workbuddy/callback", headers=auth_headers(other.id), params={
        "state": state, "code": "test-code",
    })
    assert "failed" in crossed.headers["location"]
    assert len(legacy.token_calls) == 1
    status = await api_client.get("/api/assistant/workbuddy", headers=headers)
    assert status.json()["data"]["state"] == "online"
    assert status.headers["cache-control"] == "no-store"
    assert "private-" not in status.text
    connection = (await db_session.execute(select(WorkBuddyConnection))).scalar_one()
    assert "private-access-token" not in connection.credentials
    assert "private-refresh-token" not in connection.credentials
    assert connection.state_hash is None
    connection.expires_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    assert (await api_client.get("/api/assistant/workbuddy", headers=headers)).json()["data"]["state"] == "online"
    assert legacy.token_calls[-1] == {"refresh_token": "private-refresh-token"}


# ------------------------------------------------------------------ unified roundtrip

async def test_single_direct_call_is_idempotent_shared_and_does_not_confirm_or_deduct(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, body = await start(api_client, headers, meal)
    assert job["status"] == "sending" and job["phase"] == "proposal"
    assert job["source"] == "model"
    assert model.calls == []  # start() is fast: no network

    repeated = await api_client.post("/api/assistant/adjustments", headers=headers, json=body)
    assert repeated.json()["data"]["id"] == job["id"]
    assert model.calls == []

    restored = await api_client.get("/api/assistant/adjustments/current", headers=headers, params={
        "meal_slot": meal["context"]["meal_slot"], "meal_date": meal["context"]["meal_date"],
    })
    assert restored.json()["data"]["id"] == job["id"]

    done = await poll_due(db_session, api_client, headers, job["id"])
    assert done["status"] == "completed" and done["proposal_id"]
    assert len(model.calls) == 1  # exactly ONE direct model request
    assert len(model.calls[0]["candidates"]) <= 120
    assert all("steps" not in candidate for candidate in model.calls[0]["candidates"])

    repeated_poll = await api_client.get(f"/api/assistant/adjustments/{job['id']}", headers=headers)
    assert repeated_poll.json()["data"]["proposal_id"] == done["proposal_id"]
    assert len(model.calls) == 1  # repeated poll never calls the model again

    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["revision"] == meal["revision"] + 1
    assert current["proposal"]["id"] == done["proposal_id"]
    assert current["proposal"]["status"] == "proposed"
    assert current["proposal"]["source"] == "assistant"
    # The model's returned condition patch was applied SERVER-SIDE after re-validation.
    assert current["context"]["mode"] == "takeout" and current["context"]["max_spice"] == 0
    assert (await db_session.execute(select(MealStockMovement))).scalars().all() == []
    kinds = (await db_session.execute(select(MealEvent.kind))).scalars().all()
    assert "accepted" not in kinds and "eaten" not in kinds
    assert "unrelated host conversation" not in json.dumps(done)


async def test_cross_user_and_skill_grant_cannot_invoke_or_read_other_users(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, body = await start(api_client, headers, meal)
    other = await make_user(db_session, open_id="other-workbuddy-user")
    await db_session.commit()
    other_headers = auth_headers(other.id)
    for suffix, method in (("", "get"), ("/cancel", "post")):
        response = await getattr(api_client, method)(f"/api/assistant/adjustments/{job['id']}{suffix}", headers=other_headers)
        assert response.status_code == 404
    assert (await api_client.post("/api/assistant/adjustments", headers=other_headers, json=body)).status_code == 404
    grant = (await api_client.post("/api/assistant/grants", headers=headers, json={})).json()["data"]
    token = {"Authorization": f"Bearer {grant['token']}"}
    assert (await api_client.post("/api/assistant/adjustments", headers=token, json=body)).status_code == 401
    assert model.calls == []


@pytest.mark.parametrize("operation", ["cancel", "disconnect"])
async def test_cancel_and_disconnect_prevent_late_results(db_session, api_client, auth_headers, host, operation):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    if operation == "cancel":
        response = await api_client.post(f"/api/assistant/adjustments/{job['id']}/cancel", headers=headers)
    else:
        response = await api_client.delete("/api/assistant/workbuddy", headers=headers)
    assert response.status_code == 200
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "cancelled"
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["proposal"]["id"] == meal["proposal"]["id"]
    assert model.calls == []
    if operation == "disconnect":
        assert (await db_session.execute(select(WorkBuddyConnection))).scalar_one_or_none() is None


@pytest.mark.parametrize("failure", ["vault_unavailable", "ambiguous_call"])
async def test_unavailable_model_preserves_original_meal_and_never_blindly_resends(
    db_session, api_client, auth_headers, host, failure,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    if failure == "vault_unavailable":
        model.failure = "本机 WorkBuddy 登录态不可用"
    elif failure == "ambiguous_call":
        model.failure = "WorkBuddy 模型请求超时"
    job, body = await start(api_client, headers, meal)
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "failed" and receipt["error"]
    for _ in range(2):
        repeated = await poll_due(db_session, api_client, headers, job["id"])
        assert repeated["status"] == "failed"
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["proposal"]["id"] == meal["proposal"]["id"]
    # A failed call is NEVER auto-resent: at most one attempt got made.
    assert len(model.calls) <= 1


async def test_external_revision_change_is_not_overwritten(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    updated = await api_client.post("/api/meals/propose", headers=headers, json={
        "context": meal["context"], "expected_revision": meal["revision"],
    })
    assert updated.status_code == 200
    latest_id = updated.json()["data"]["proposal"]["id"]
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "failed" and "更新" in receipt["error"]
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["proposal"]["id"] == latest_id


@pytest.mark.parametrize("kind", ["unknown_key", "invalid_schema", "model_failure", "changed_slot", "null_condition"])
async def test_invalid_ai_results_are_explained_and_never_saved(
    db_session, api_client, auth_headers, host, kind,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    if kind == "unknown_key":
        extra = {"candidate_keys": ["invented-key"], "reason": "不要校验"}
    elif kind == "invalid_schema":
        extra = {"context": {"servings": 200}}
    elif kind == "model_failure":
        extra = {"error": "无法满足要求，请明确预算"}
    elif kind == "changed_slot":
        extra = {"context": {"meal_slot": "breakfast"}}
    else:
        extra = {"context": {"servings": None}}
    model.reply_override = lambda payload: {"request_id": payload["request_id"], "phase": "proposal", **extra}
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "failed" and receipt["error"]
    proposals = (await db_session.execute(select(MealProposal))).scalars().all()
    assert len(proposals) == 1 and proposals[0].id == meal["proposal"]["id"]


async def test_wrong_request_reply_is_ignored_and_timeout_is_terminal(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    model.reply_override = lambda payload: {"request_id": str(uuid4()), "phase": "proposal", "candidate_keys": [], "reason": "x"}
    failed = await poll_due(db_session, api_client, headers, job["id"])
    assert failed["status"] == "failed"
    assert len(model.calls) == 1


async def test_concurrent_polls_do_not_duplicate_model_calls_or_proposals(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    body = {
        "request_id": str(uuid4()), "instruction": "两个人，不开火，不辣",
        "context": meal["context"], "expected_revision": meal["revision"],
    }
    responses = await asyncio.gather(*[
        api_client.post("/api/assistant/adjustments", headers=headers, json=body) for _ in range(3)
    ])
    assert all(response.status_code == 200 for response in responses)
    assert model.calls == []
    job_id = body["request_id"]
    row = (await db_session.execute(
        select(AssistantAdjustment).execution_options(populate_existing=True),
    )).scalar_one()
    row.next_poll_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    polled = await asyncio.gather(*[
        api_client.get(f"/api/assistant/adjustments/{job_id}", headers=headers) for _ in range(3)
    ])
    assert all(response.status_code == 200 for response in polled)
    final = (await api_client.get(f"/api/assistant/adjustments/{job_id}", headers=headers)).json()["data"]
    assert final["status"] == "completed"
    assert len(model.calls) == 1, "concurrent polls must not duplicate the paid model call"
    assert len((await db_session.execute(select(MealProposal))).scalars().all()) == 2


async def test_disconnect_during_model_call_wins_over_late_result(
    db_session, api_client, auth_headers, host,
):
    model, _ = host
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    entered, resume = asyncio.Event(), asyncio.Event()
    model.blocking = (entered, resume)
    row = (await db_session.execute(
        select(AssistantAdjustment).execution_options(populate_existing=True),
    )).scalar_one()
    row.next_poll_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    poll = asyncio.create_task(api_client.get(f"/api/assistant/adjustments/{job['id']}", headers=headers))
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        response = await api_client.delete("/api/assistant/workbuddy", headers=headers)
        assert response.status_code == 200
    finally:
        resume.set()
    result = await poll
    assert result.json()["data"]["status"] == "cancelled"
    assert len((await db_session.execute(select(MealProposal))).scalars().all()) == 1


async def test_disconnect_during_oauth_exchange_does_not_reconnect(
    db_session, api_client, auth_headers, host,
):
    _, legacy = host
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/assistant/workbuddy/authorize", headers=headers)
    state = parse_qs(urlsplit(response.json()["data"]["url"]).query)["state"][0]
    entered, resume = asyncio.Event(), asyncio.Event()
    original = legacy.token

    async def delayed(**kwargs):
        entered.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return await original(**kwargs)

    legacy.token = delayed
    callback = asyncio.create_task(api_client.get(
        "/api/assistant/workbuddy/callback", headers=headers, params={"state": state, "code": "code"},
    ))
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        assert (await api_client.delete("/api/assistant/workbuddy", headers=headers)).status_code == 200
    finally:
        resume.set()
    result = await callback
    assert "failed" in result.headers["location"]
    assert (await db_session.execute(select(WorkBuddyConnection))).scalar_one_or_none() is None


async def test_new_allergy_during_waiting_invalidates_previously_offered_candidates(
    db_session, api_client, auth_headers, host,
):
    """An allergy added AFTER the task was created must still block the write.

    The unified path recomputes/validates candidates inside propose(), so a
    server-side restriction added while the task waits cannot be overridden by
    the model's earlier candidate list.
    """
    model, _ = host
    user, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    candidates = (await db_session.execute(
        select(AssistantAdjustment).execution_options(populate_existing=True),
    )).scalar_one().payload["candidates"]
    offered = next(dish for dish in candidates if dish["role"] == "complete")
    db_session.add(AllergyRestriction(
        user_id=user.id, allergens=json.dumps(offered["ingredients"], ensure_ascii=False),
    ))
    await db_session.commit()
    failed = await poll_due(db_session, api_client, headers, job["id"])
    assert failed["status"] == "failed" and "忌口" in failed["error"]
    assert len((await db_session.execute(select(MealProposal))).scalars().all()) == 1
