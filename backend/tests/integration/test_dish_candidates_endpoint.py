"""真打端点的冒烟：POST /api/assistant/candidates。

「831 条测试全绿但端点实际 500」是本项目踩过的坑 —— 核心端点必须有真正
发 HTTP 请求、真正走完依赖注入与落库的用例，不能只测服务函数。
"""
from __future__ import annotations

import io
import json
from zipfile import ZipFile

import pytest
from app.config import Settings, WorkBuddySettings
from app.models.recipe import Recipe, RecipeEnrichLog
from app.services import dish_candidate_skill as skill
from app.services.workbuddy_model_client import (
    ChatEnvelope,
    WorkBuddyModelClient,
    get_workbuddy_model_client,
)
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql

BASIS = "粤菜家常煲汤，冬瓜配排骨小火慢炖，常见于两广家庭餐桌"
NAMES = ("冬瓜排骨汤", "番茄牛腩", "紫菜蛋花汤", "虾仁滑蛋", "香菇青菜")
STEPS = [
    "排骨冷水下锅焯水，撇去浮沫后捞出",
    "冬瓜去皮切块，姜切片备用",
    "排骨与姜片加水大火烧开，转小火炖四十分钟",
    "放入冬瓜再炖十五分钟，加盐调味",
]


def _dish(name: str) -> dict:
    return {
        "name": name, "cuisine": "家常", "category": "汤羹",
        "main_ingredient": "排骨", "cook_minutes": 55, "spice_level": 0,
        "is_light": True, "ingredients": ["冬瓜", "排骨"],
        "quick_steps": ["排骨焯水", "冬瓜切块", "同炖"], "steps": list(STEPS),
        "reality_basis": BASIS,
    }


class FakeCandidateModel(WorkBuddyModelClient):
    """One canned, valid reply; records every prompt so latency claims are testable."""

    def __init__(self):
        super().__init__(Settings(workbuddy=WorkBuddySettings(model_timeout_seconds=10)))
        self.calls: list[str] = []
        self.failure = None

    async def chat(self, prompt: str, *, model: str = "") -> ChatEnvelope:
        self.calls.append(prompt)
        if self.failure:
            return ChatEnvelope.failure(502, "server", self.failure)
        data = json.loads(prompt.splitlines()[-1])
        count = data.get("count", skill.DEFAULT_COUNT)
        items = [_dish(NAMES[i]) for i in range(min(count, len(NAMES)))]
        return ChatEnvelope.success(
            json.dumps({"candidates": items}, ensure_ascii=False),
            model="hy4free", region="cn",
        )


@pytest.fixture
def host():
    from app.main import app

    model = FakeCandidateModel()
    app.dependency_overrides[get_workbuddy_model_client] = lambda: model
    yield model
    app.dependency_overrides.pop(get_workbuddy_model_client, None)


async def _user(db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_candidate_skill")
    await db_session.commit()
    return auth_headers(user.id)


async def test_endpoint_returns_four_structured_candidates_in_one_call(
    db_session, api_client, auth_headers, host,
):
    headers = await _user(db_session, auth_headers)
    response = await api_client.post("/api/assistant/candidates", headers=headers, json={
        "description": "两个人，想吃点暖胃的，别太辣",
        "context": {"servings": 2, "max_spice": 1},
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["skill"] == skill.SKILL_NAME
    assert data["count"] == skill.DEFAULT_COUNT == 4
    assert data["degraded"] is False and data["reason"] == ""
    assert all(set(item) == set(skill.CANDIDATE_FIELDS) for item in data["candidates"])
    assert data["candidates"][0]["reality_basis"] == BASIS
    # 单跳低延迟：没有任务、没有轮询、没有第二次模型请求。
    assert len(host.calls) == 1
    assert host.calls[0].startswith(skill.PROMPT_LEAD)
    payload = json.loads(host.calls[0].splitlines()[-1])
    assert payload["task_type"] == skill.TASK_TYPE
    assert payload["context"] == {"servings": 2, "max_spice": 1}


async def test_endpoint_validates_count_bounds_and_accepts_three(
    db_session, api_client, auth_headers, host,
):
    headers = await _user(db_session, auth_headers)
    for bad in (2, 6, 0):
        response = await api_client.post("/api/assistant/candidates", headers=headers, json={
            "description": "来点下饭的", "count": bad,
        })
        assert response.status_code == 422, (bad, response.text)
    ok = await api_client.post("/api/assistant/candidates", headers=headers, json={
        "description": "来点下饭的", "count": 3,
    })
    assert ok.status_code == 200 and ok.json()["data"]["count"] == 3


async def test_endpoint_requires_login(api_client, host):
    response = await api_client.post("/api/assistant/candidates", json={"description": "想喝汤"})
    assert response.status_code == 401
    assert host.calls == []


async def test_endpoint_degrades_cleanly_when_model_is_unavailable(
    db_session, api_client, auth_headers, host,
):
    headers = await _user(db_session, auth_headers)
    host.failure = "上游限流"
    response = await api_client.post("/api/assistant/candidates", headers=headers, json={
        "description": "想喝汤",
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidates"] == [] and data["degraded"] is True
    assert "上游限流" in data["reason"]
    assert len(host.calls) == 1, "失败不重发"


async def test_persist_writes_only_validated_dishes_with_evidence(
    db_session, api_client, auth_headers, host,
):
    headers = await _user(db_session, auth_headers)
    response = await api_client.post("/api/assistant/candidates", headers=headers, json={
        "description": "想吃点暖胃的汤", "count": 3, "persist": True,
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["persisted"] == [item["name"] for item in data["candidates"]]
    assert all(item["key"].startswith("recipe:") for item in data["candidates"])

    await db_session.rollback()  # 让本会话看到 get_db 已提交的行
    rows = (await db_session.execute(select(Recipe).where(Recipe.source == "ai_generated"))).scalars().all()
    assert len(rows) == 3
    assert all(row.reality_basis == BASIS for row in rows)
    assert all(row.generated_for == "想吃点暖胃的汤" for row in rows)
    assert all(row.is_dish is True for row in rows)
    logs = (await db_session.execute(
        select(RecipeEnrichLog).where(RecipeEnrichLog.kind == "expand")
    )).scalars().all()
    assert len(logs) == 3


async def test_skill_zip_bundles_the_candidate_contract(
    db_session, api_client, auth_headers, host,
):
    headers = await _user(db_session, auth_headers)
    response = await api_client.get("/api/assistant/skill.zip", headers=headers)
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert "fandecide/SKILL.md" in names
    assert "fandecide/candidates/SKILL.md" in names
    assert "fandecide/candidates/contract.json" in names
