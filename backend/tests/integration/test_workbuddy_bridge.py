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
from app.services.workbuddy_client import SCOPES, WorkBuddyClient, WorkBuddyError, get_workbuddy_client
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql


class FakeWorkBuddy(WorkBuddyClient):
    def __init__(self):
        super().__init__(Settings(
            workbuddy=WorkBuddySettings(
                client_id="test-app", client_secret="private-client-secret",
                redirect_uri="http://127.0.0.1:5173/api/assistant/workbuddy/callback",
            ),
            auth={"jwt_secret": "test-credential-encryption-key-32-characters"},
        ))
        self.sent = []
        self.token_calls = []
        self.is_online = True
        self.patch = {"mode": "takeout", "servings": 2, "max_spice": 0}
        self.reply_override = None
        self.send_error = None
        self.poll_error = None

    async def token(self, **kwargs):
        self.token_calls.append(kwargs)
        return {
            "access_token": "private-access-token", "refresh_token": "private-refresh-token",
            "expires_in": 3600, "scope": " ".join(SCOPES),
        }

    async def online(self, token):
        assert token == "private-access-token"
        return self.is_online

    async def send(self, token, content):
        if self.send_error:
            raise self.send_error
        self.sent.append(json.loads(content.splitlines()[-1]))
        assert "private-access-token" not in content and "fd_skill_" not in content
        return f"message-{len(self.sent)}"

    async def messages(self, token, message_id):
        if self.poll_error:
            raise self.poll_error
        prompt = self.sent[int(message_id.split("-")[-1]) - 1]
        if self.reply_override:
            reply = self.reply_override(prompt)
        elif prompt["phase"] == "context":
            reply = {"request_id": prompt["request_id"], "phase": "context", "context": self.patch}
        else:
            complete = next(d for d in prompt["candidates"] if d["role"] == "complete")
            side = next(d for d in prompt["candidates"] if d["role"] == "side")
            reply = {
                "request_id": prompt["request_id"], "phase": "proposal",
                "candidate_keys": [complete["key"], side["key"]], "reason": "按两人、不辣和外卖要求搭配",
            }
        return [
            {"role": "assistant", "msg_type": "text", "content": ['{"private":"unrelated host conversation"}']},
            {"role": "assistant", "msg_type": "text", "content": [json.dumps(reply, ensure_ascii=False)]},
        ]


@pytest.fixture
def host():
    from app.main import app

    fake = FakeWorkBuddy()
    app.dependency_overrides[get_workbuddy_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_workbuddy_client, None)


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


async def test_oauth_state_is_single_use_bound_to_user_and_tokens_stay_encrypted(
    db_session, api_client, auth_headers, host,
):
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
    assert len(host.token_calls) == 1
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
    assert host.token_calls[-1] == {"refresh_token": "private-refresh-token"}


async def test_two_turn_roundtrip_is_idempotent_shared_and_does_not_confirm_or_deduct(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, body = await start(api_client, headers, meal)
    assert job["status"] == "waiting" and job["phase"] == "context"
    repeated = await api_client.post("/api/assistant/adjustments", headers=headers, json=body)
    assert repeated.json()["data"]["id"] == job["id"]
    assert len(host.sent) == 1
    restored = await api_client.get("/api/assistant/adjustments/current", headers=headers, params={
        "meal_slot": meal["context"]["meal_slot"], "meal_date": meal["context"]["meal_date"],
    })
    assert restored.json()["data"]["id"] == job["id"]
    stage2 = await poll_due(db_session, api_client, headers, job["id"])
    assert stage2["phase"] == "proposal" and stage2["status"] == "waiting"
    assert len(host.sent[-1]["candidates"]) <= 120
    assert all("steps" not in candidate for candidate in host.sent[-1]["candidates"])
    done = await poll_due(db_session, api_client, headers, job["id"])
    assert done["status"] == "completed" and done["proposal_id"]
    repeated = await api_client.get(f"/api/assistant/adjustments/{job['id']}", headers=headers)
    assert repeated.json()["data"]["proposal_id"] == done["proposal_id"]
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["revision"] == meal["revision"] + 1
    assert current["proposal"]["id"] == done["proposal_id"]
    assert current["proposal"]["status"] == "proposed"
    assert current["proposal"]["source"] == "assistant"
    assert current["context"]["mode"] == "takeout" and current["context"]["servings"] == 2
    assert current["context"]["max_spice"] == 0
    assert (await db_session.execute(select(MealStockMovement))).scalars().all() == []
    kinds = (await db_session.execute(select(MealEvent.kind))).scalars().all()
    assert "accepted" not in kinds and "eaten" not in kinds
    assert "unrelated host conversation" not in json.dumps(done)
    assert len(host.sent) == 2


async def test_cross_user_grant_and_request_ids_cannot_invoke_or_read_other_users(
    db_session, api_client, auth_headers, host,
):
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
    assert len(host.sent) == 1


@pytest.mark.parametrize("operation", ["cancel", "disconnect"])
async def test_cancel_and_disconnect_prevent_late_results(db_session, api_client, auth_headers, host, operation):
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
    assert len(host.sent) == 1
    if operation == "disconnect":
        assert (await db_session.execute(select(WorkBuddyConnection))).scalar_one_or_none() is None


@pytest.mark.parametrize("failure", ["missing_authorization", "offline", "ambiguous_send"])
async def test_unavailable_assistant_preserves_original_meal_and_never_blindly_resends(
    db_session, api_client, auth_headers, host, failure,
):
    _, headers, meal = await setup_meal(
        db_session, api_client, auth_headers, connected=failure != "missing_authorization",
    )
    host.is_online = failure != "offline"
    if failure == "ambiguous_send":
        host.send_error = WorkBuddyError("发送状态不明", transient=True)
    job, body = await start(api_client, headers, meal)
    assert job["status"] == "failed"
    assert job["error"]
    for _ in range(2):
        repeated = await api_client.post("/api/assistant/adjustments", headers=headers, json=body)
        assert repeated.json()["data"]["status"] == "failed"
    current = (await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)).json()["data"]
    assert current["proposal"]["id"] == meal["proposal"]["id"]
    assert host.sent == []


async def test_external_revision_change_and_invalid_reply_never_overwrite(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    await poll_due(db_session, api_client, headers, job["id"])
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
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    if kind == "unknown_key":
        await poll_due(db_session, api_client, headers, job["id"])
        extra = {"candidate_keys": ["invented-key"], "reason": "不要校验"}
    elif kind == "invalid_schema":
        extra = {"context": {"servings": 200}}
    elif kind == "model_failure":
        extra = {"error": "无法满足要求，请明确预算"}
    elif kind == "changed_slot":
        extra = {"context": {"meal_slot": "breakfast"}}
    else:
        extra = {"context": {"servings": None}}
    host.reply_override = lambda prompt: {"request_id": prompt["request_id"], "phase": prompt["phase"], **extra}
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "failed" and receipt["error"]
    proposals = (await db_session.execute(select(MealProposal))).scalars().all()
    assert len(proposals) == 1 and proposals[0].id == meal["proposal"]["id"]


async def test_wrong_request_reply_is_ignored_timeout_is_terminal_and_poll_errors_back_off(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    host.reply_override = lambda prompt: {"request_id": str(uuid4()), "phase": "context", "context": {"servings": 20}}
    waiting = await poll_due(db_session, api_client, headers, job["id"])
    assert waiting["status"] == "waiting"
    host.poll_error = WorkBuddyError("请求较多", transient=True)
    receipt = await poll_due(db_session, api_client, headers, job["id"])
    assert receipt["status"] == "waiting" and receipt["poll_after_ms"] >= 5000
    row = (await db_session.execute(select(AssistantAdjustment))).scalar_one()
    row.expires_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    expired = await api_client.get(f"/api/assistant/adjustments/{job['id']}", headers=headers)
    assert expired.json()["data"]["status"] == "failed"
    assert len(host.sent) == 1


async def test_concurrent_start_and_poll_do_not_duplicate_messages_or_proposals(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    body = {
        "request_id": str(uuid4()), "instruction": "两个人，不开火，不辣",
        "context": meal["context"], "expected_revision": meal["revision"],
    }
    responses = await asyncio.gather(*[
        api_client.post("/api/assistant/adjustments", headers=headers, json=body) for _ in range(3)
    ])
    assert all(response.status_code == 200 for response in responses)
    assert len(host.sent) == 1
    job_id = body["request_id"]
    await poll_due(db_session, api_client, headers, job_id)
    assert len(host.sent) == 2
    row = (await db_session.execute(
        select(AssistantAdjustment).execution_options(populate_existing=True),
    )).scalar_one()
    row.next_poll_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    responses = await asyncio.gather(*[
        api_client.get(f"/api/assistant/adjustments/{job_id}", headers=headers) for _ in range(3)
    ])
    assert all(response.status_code == 200 for response in responses)
    final = (await api_client.get(f"/api/assistant/adjustments/{job_id}", headers=headers)).json()["data"]
    assert final["status"] == "completed"
    assert len((await db_session.execute(select(MealProposal))).scalars().all()) == 2
    assert len(host.sent) == 2


async def test_disconnect_during_remote_reply_wins_over_late_result(
    db_session, api_client, auth_headers, host,
):
    _, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    await poll_due(db_session, api_client, headers, job["id"])
    row = (await db_session.execute(
        select(AssistantAdjustment).execution_options(populate_existing=True),
    )).scalar_one()
    row.next_poll_at = meal_now() - timedelta(seconds=1)
    await db_session.commit()
    entered, resume = asyncio.Event(), asyncio.Event()
    original = host.messages

    async def delayed(*args):
        entered.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return await original(*args)

    host.messages = delayed
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
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/assistant/workbuddy/authorize", headers=headers)
    state = parse_qs(urlsplit(response.json()["data"]["url"]).query)["state"][0]
    entered, resume = asyncio.Event(), asyncio.Event()
    original = host.token

    async def delayed(**kwargs):
        entered.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return await original(**kwargs)

    host.token = delayed
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
    user, headers, meal = await setup_meal(db_session, api_client, auth_headers)
    job, _ = await start(api_client, headers, meal)
    await poll_due(db_session, api_client, headers, job["id"])
    offered = next(dish for dish in host.sent[-1]["candidates"] if dish["role"] == "complete")
    db_session.add(AllergyRestriction(
        user_id=user.id, allergens=json.dumps(offered["ingredients"], ensure_ascii=False),
    ))
    await db_session.commit()
    failed = await poll_due(db_session, api_client, headers, job["id"])
    assert failed["status"] == "failed" and "忌口" in failed["error"]
    assert len((await db_session.execute(select(MealProposal))).scalars().all()) == 1
