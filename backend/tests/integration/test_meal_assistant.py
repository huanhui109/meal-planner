from __future__ import annotations

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql


async def test_mysql_assistant_grant_roundtrip(db_session, api_client, auth_headers):
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/assistant/grants", headers=headers, json={})
    assert response.status_code == 200, response.text
    grant = response.json()["data"]
    assert grant["created_at"] and grant["token"].startswith("fd_skill_")
    token_headers = {"Authorization": f"Bearer {grant['token']}"}
    response = await api_client.post("/api/assistant/context", headers=token_headers, json={
        "meal_slot": "dinner", "servings": 1, "max_minutes": 60,
    })
    assert response.status_code == 200, response.text
    context = response.json()["data"]
    candidate = next(dish for dish in context["candidates"] if dish["role"] == "complete")
    saved = await api_client.post("/api/assistant/proposals", headers=token_headers, json={
        "context": context["context"], "expected_revision": context["revision"],
        "candidate_keys": [candidate["key"]], "reason": "按要求搭配这一餐",
    })
    assert saved.status_code == 200, saved.text
    proposal = saved.json()["data"]["proposal"]
    assert proposal["created_at"] and proposal["source"] == "assistant"
    shared = await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)
    assert shared.json()["data"]["proposal"]["id"] == proposal["id"]
    assert (await api_client.post(
        f"/api/meals/{proposal['id']}/accept", headers=token_headers, json={"expected_revision": 1},
    )).status_code == 401
    assert (await api_client.delete(f"/api/assistant/grants/{grant['id']}", headers=headers)).status_code == 200
    assert (await api_client.post("/api/assistant/context", headers=token_headers, json={})).status_code == 401
