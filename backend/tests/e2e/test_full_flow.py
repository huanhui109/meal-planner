"""端到端验收: 登录 -> 偏好 -> 生成 -> 周视图 -> 换菜/锁定 -> 采购 -> 已做 -> 库存同步

生成 worker 在测试中不常驻, 这里手动领取并执行一次任务,
走的仍是生产同一条状态机与落库路径。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List

from sqlalchemy import select

from app.auth.feishu_oauth import get_feishu_oauth_client
from app.llm.base import LLMClient
from app.models.menu import MenuItem, MenuStatus
from app.models.user import User
from app.services import generation_service
from tests.conftest import requires_mysql
from tests.factories import make_ingredient, week_start_of

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


class FakeFeishuClient:
    def build_authorize_url(self, state: str) -> str:
        return f"https://open.feishu.cn/open-apis/authen/v1/index?state={state}"

    async def login(self, code: str) -> Dict[str, Any]:
        return {"open_id": "ou_e2e", "union_id": "un_e2e", "name": "端到端用户"}


class FakeLLM(LLMClient):
    def __init__(self, payload: Dict[str, Any]):
        super().__init__("fake")
        self.payload = payload

    async def chat(self, messages, temperature=0.7, max_tokens=4000) -> str:
        return json.dumps(self.payload, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True


def _full_week_payload() -> Dict[str, Any]:
    days: List[Dict[str, Any]] = []
    for offset in range(7):
        day = WEEK_START + timedelta(days=offset)
        days.append(
            {
                "date": str(day),
                "day_type": "weekend" if day.weekday() >= 5 else "weekday",
                "meals": {
                    "dinner": {
                        "recipes": [
                            {
                                "name": f"香煎鸡胸西兰花 {offset + 1}",
                                "ingredients": [
                                    {"name": "鸡胸肉", "quantity": "200g", "unit": ""},
                                    {"name": "西兰花", "quantity": "300g", "unit": ""},
                                ],
                                "calories": 480,
                                "protein_g": 45.0,
                                "carb_g": 30.0,
                                "fat_g": 14.0,
                                "cook_minutes": 25,
                                "steps": "鸡胸煎熟, 西兰花焯水后同炒",
                            }
                        ]
                    }
                },
            }
        )
    return {"week_menu": days}


async def test_full_user_journey(api_client, db_session, auth_headers, monkeypatch):
    from app.main import app

    app.dependency_overrides[get_feishu_oauth_client] = lambda: FakeFeishuClient()
    try:
        login = await api_client.get("/api/auth/feishu/callback", params={"code": "e2e-code"})
    finally:
        app.dependency_overrides.pop(get_feishu_oauth_client, None)
    assert login.status_code == 307

    await db_session.rollback()
    user = (await db_session.execute(select(User).where(User.open_id == "ou_e2e"))).scalar_one()
    user_id = user.id
    headers = auth_headers(user_id)

    me = await api_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200

    for path, body in (
        (
            "/api/preferences/household",
            {
                "member_count": 2,
                "meals_per_day": 2,
                "kitchen_equipments": ["灶台"],
                "weekday_cook_minutes": 30,
                "weekend_cook_minutes": 60,
            },
        ),
        (
            "/api/preferences/diet",
            {"cuisines": ["家常菜"], "spice_level": 2, "flavor_preference": "清淡"},
        ),
        (
            "/api/preferences/allergy",
            {"allergens": [], "avoid_ingredients": [], "dietary_restrictions": ""},
        ),
        (
            "/api/preferences/health-goal",
            {"goal_type": "减脂", "daily_calories": 1600, "protein_pct": 30, "carb_pct": 40, "fat_pct": 30},
        ),
        (
            "/api/preferences/budget",
            {"weekday_daily_budget": 40.0, "weekend_daily_budget": 80.0, "weekly_cap": 400.0},
        ),
    ):
        saved = await api_client.put(path, json=body, headers=headers)
        assert saved.status_code == 200, path

    await make_ingredient(db_session, "鸡胸肉", unit="g", price=0.03)
    await make_ingredient(db_session, "西兰花", unit="g", price=0.02)
    await db_session.commit()

    submitted = await api_client.post(
        "/api/menus/generate",
        json={"week_start": str(WEEK_START), "force": True},
        headers=headers,
    )
    assert submitted.status_code == 202
    task_id = submitted.json()["data"]["task_id"]

    monkeypatch.setattr(generation_service, "build_fallback_chain", lambda settings: FakeLLM(_full_week_payload()))
    worker = generation_service.GenerationWorker()
    claimed = await worker._claim()
    assert claimed == task_id, "worker 应领取到刚提交的任务"
    await worker._execute(claimed)

    task = await api_client.get(f"/api/menus/generation-tasks/{task_id}", headers=headers)
    assert task.json()["data"]["status"] == "succeeded"
    menu_id = task.json()["data"]["menu_id"]
    assert menu_id

    current = await api_client.get("/api/menus/current", headers=headers)
    assert current.status_code == 200
    menu = current.json()["data"]
    assert len(menu["days"]) == 7
    assert menu["totals"]["meal_count"] == 7
    assert menu["totals"]["estimated_cost"] == round(7 * (200 * 0.03 + 300 * 0.02), 2)
    assert menu["nutrition"]["days_count"] == 7

    target_item = menu["days"][0]["meals"][0]
    replaced = await api_client.put(
        f"/api/menus/{menu_id}/items/{target_item['id']}/replace",
        json={
            "recipe_name": "清炒时蔬",
            "recipe_ingredients": [{"name": "西兰花", "quantity": "400g", "unit": ""}],
            "calories": 200,
            "cook_minutes": 10,
            "steps": "清炒",
        },
        headers=headers,
    )
    assert replaced.status_code == 200
    assert replaced.json()["data"]["days"][0]["meals"][0]["recipe"]["name"] == "清炒时蔬"

    locked = await api_client.put(
        f"/api/menus/{menu_id}/items/{target_item['id']}/lock", headers=headers
    )
    assert locked.json()["data"]["is_locked"] is True

    confirmed = await api_client.post(f"/api/menus/{menu_id}/confirm", headers=headers)
    assert confirmed.json()["data"]["status"] == MenuStatus.CONFIRMED

    shopping = await api_client.get(f"/api/menus/{menu_id}/shopping-list", headers=headers)
    assert shopping.status_code == 200
    shopping_data = shopping.json()["data"]
    to_buy = {item["name"] for item in shopping_data["items"] if not item["have_enough"]}
    assert "鸡胸肉" in to_buy, "没有库存的食材应出现在需买清单"
    assert shopping_data["summary"]["to_buy_count"] >= 1

    cooked_item = menu["days"][1]["meals"][0]
    cooked = await api_client.put(
        f"/api/menus/{menu_id}/items/{cooked_item['id']}/cooked", headers=headers
    )
    assert cooked.status_code == 200
    assert cooked.json()["data"]["already_cooked"] is False
    assert cooked.json()["data"]["missing"], "鸡胸肉无库存, 应返回缺料明细"

    inventory = await api_client.get("/api/inventory", headers=headers)
    assert inventory.status_code == 200

    after = await api_client.get("/api/menus/current", headers=headers)
    assert after.json()["data"]["totals"]["cooked_count"] == 1
    assert after.json()["data"]["budget"]["budget_limit"] == 400.0

    await db_session.rollback()
    all_items = (
        await db_session.execute(select(MenuItem).where(MenuItem.menu_id == menu_id))
    ).scalars().all()
    assert sum(1 for item in all_items if item.is_cooked) == 1
    assert sum(1 for item in all_items if item.is_locked) == 1
