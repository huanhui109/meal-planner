"""集成测试: 生成流水线落库、过敏源剔除、成本与配额"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from app.config import get_settings
from app.llm.base import LLMClient
from app.models.menu import Menu, MenuGenerationTask, MenuItem, MenuStatus
from app.models.recipe import Recipe, RecipeIngredient
from app.services.generation_service import MenuGenerationPipeline
from sqlalchemy import func, select

from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_preferences, make_user, week_start_of

pytestmark = requires_mysql


class FakeLLM(LLMClient):
    """替身: 直接返回预置的周菜单 JSON, 不发起网络调用"""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__("fake")
        self.payload = payload
        self.calls = 0
        self.messages: List[List[Dict[str, str]]] = []

    async def chat(self, messages, temperature=0.7, max_tokens=4000) -> str:
        self.calls += 1
        self.messages.append(messages)
        import json

        return json.dumps(self.payload, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True


def recipe_payload(
    name: str,
    ingredients: List[Dict[str, Any]],
    calories: int = 500,
    protein_g: float = 30.0,
    carb_g: float = 50.0,
    fat_g: float = 15.0,
) -> Dict[str, Any]:
    return {
        "name": name,
        "ingredients": ingredients,
        "calories": calories,
        "protein_g": protein_g,
        "carb_g": carb_g,
        "fat_g": fat_g,
        "cook_minutes": 20,
        "steps": "炒熟调味",
    }


def week_payload(week_start: date, recipes_per_day: List[Dict[str, Any]]) -> Dict[str, Any]:
    days = []
    for offset, recipe in enumerate(recipes_per_day):
        days.append(
            {
                "date": str(week_start + timedelta(days=offset)),
                "day_type": "weekend" if (week_start + timedelta(days=offset)).weekday() >= 5 else "weekday",
                "meals": {"dinner": {"recipes": [recipe]}},
            }
        )
    return {"week_menu": days}


async def _seed_ingredients(db, ingredients) -> None:
    for name, unit, price in ingredients:
        await make_ingredient(db, name, unit=unit, price=price)
    await db.flush()


async def test_pipeline_persists_ingredients_and_cost(db_session):
    user = await make_user(db_session, open_id="ou_gen_1")
    await make_preferences(db_session, user.id)
    await _seed_ingredients(db_session, [("番茄", "g", 0.02), ("鸡蛋", "个", 1.5)])
    await db_session.commit()

    week_start = week_start_of(date(2026, 1, 5))
    llm = FakeLLM(
        week_payload(
            week_start,
            [
                recipe_payload(
                    "番茄炒蛋",
                    [
                        {"name": "番茄", "quantity": "200g", "unit": ""},
                        {"name": "鸡蛋", "quantity": "2个", "unit": ""},
                    ],
                )
            ],
        )
    )
    outcome = await MenuGenerationPipeline(llm).run(user.id, week_start)

    assert llm.calls >= 1
    assert outcome.menu_id

    await db_session.rollback()
    recipe = (
        await db_session.execute(select(Recipe).where(Recipe.name == "番茄炒蛋"))
    ).scalar_one()
    rows = (
        await db_session.execute(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
        )
    ).scalars().all()
    amounts = {(r.quantity, r.unit) for r in rows}
    assert (200.0, "g") in amounts
    assert (2.0, "个") in amounts

    item = (
        await db_session.execute(select(MenuItem).where(MenuItem.menu_id == outcome.menu_id))
    ).scalar_one()
    assert item.estimated_cost == 7.0


async def test_allergen_recipes_are_excluded_with_warning(db_session):
    user = await make_user(db_session, open_id="ou_gen_2")
    await make_preferences(db_session, user.id, allergens=["花生"])
    await _seed_ingredients(db_session, [("花生", "g", 0.03), ("黄瓜", "g", 0.01)])
    await db_session.commit()

    week_start = week_start_of(date(2026, 1, 5))
    llm = FakeLLM(
        week_payload(
            week_start,
            [
                recipe_payload("凉拌花生", [{"name": "花生", "quantity": "100g", "unit": ""}]),
                recipe_payload("拍黄瓜", [{"name": "黄瓜", "quantity": "200g", "unit": ""}]),
            ],
        )
    )
    outcome = await MenuGenerationPipeline(llm).run(user.id, week_start)

    assert any("过敏源" in w for w in outcome.warnings)

    await db_session.rollback()
    names = (
        await db_session.execute(
            select(Recipe.name)
            .join(MenuItem, MenuItem.recipe_id == Recipe.id)
            .where(MenuItem.menu_id == outcome.menu_id)
        )
    ).scalars().all()
    assert names == ["拍黄瓜"]


async def test_nutrition_day_count_matches_menu_days(db_session):
    """回归: days 曾经恒为 0"""
    user = await make_user(db_session, open_id="ou_gen_3")
    await make_preferences(db_session, user.id, daily_calories=1000)
    await _seed_ingredients(db_session, [("西兰花", "g", 0.02)])
    await db_session.commit()

    week_start = week_start_of(date(2026, 1, 5))
    llm = FakeLLM(
        week_payload(
            week_start,
            [
                recipe_payload("白灼西兰花", [{"name": "西兰花", "quantity": "300g", "unit": ""}]),
                recipe_payload("蒜蓉西兰花", [{"name": "西兰花", "quantity": "300g", "unit": ""}]),
            ],
        )
    )
    outcome = await MenuGenerationPipeline(llm).run(user.id, week_start)

    assert outcome.nutrition.days_count == 2
    assert outcome.nutrition.weekly_avg_calories == 500.0


async def test_amount_text_keeps_original_wording(db_session):
    user = await make_user(db_session, open_id="ou_gen_4")
    await make_preferences(db_session, user.id)
    await _seed_ingredients(db_session, [("盐", "g", 0.003)])
    await db_session.commit()

    week_start = week_start_of(date(2026, 1, 5))
    llm = FakeLLM(
        week_payload(
            week_start,
            [recipe_payload("清炒时蔬", [{"name": "盐", "quantity": "适量", "unit": ""}])],
        )
    )
    await MenuGenerationPipeline(llm).run(user.id, week_start)

    await db_session.rollback()
    row = (await db_session.execute(select(RecipeIngredient))).scalars().first()
    assert row is not None
    assert row.quantity is None
    assert row.amount_text == "适量"


async def test_generate_endpoint_enqueues_task_and_enforces_quota(api_client, db_session, auth_headers):
    """首次生成: 每天 3 次, 第 4 次 429"""
    user = await make_user(db_session, open_id="ou_quota")
    await db_session.commit()
    headers = auth_headers(user.id)
    body = {"week_start": "2026-01-05"}

    accepted = await api_client.post("/api/menus/generate", json=body, headers=headers)
    assert accepted.status_code == 202
    task_id = accepted.json()["data"]["task_id"]
    assert accepted.json()["data"]["reused"] is False

    for _ in range(2):
        response = await api_client.post("/api/menus/generate", json=body, headers=headers)
        assert response.status_code == 202

    blocked = await api_client.post("/api/menus/generate", json=body, headers=headers)
    assert blocked.status_code == 429
    assert "生成次数" in blocked.json()["detail"]

    status_response = await api_client.get(
        f"/api/menus/generation-tasks/{task_id}", headers=headers
    )
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "pending"

    await db_session.rollback()
    total = (
        await db_session.execute(
            select(func.count(MenuGenerationTask.id)).where(
                MenuGenerationTask.is_regeneration.is_(False)
            )
        )
    ).scalar_one()
    assert total == 3


async def test_regeneration_uses_its_own_quota(api_client, db_session, auth_headers):
    """重新生成有独立额度: 连换 4 次也不该被「首次生成 3 次」挡住

    回归用例 —— 之前两者共用配额, 用户在同一周里换两次菜就被 429 卡住。
    """
    user = await make_user(db_session, open_id="ou_regen_quota")
    await db_session.commit()
    headers = auth_headers(user.id)
    body = {"week_start": "2026-01-05", "force": True}
    limit = get_settings().menu.daily_regenerate_limit

    for _ in range(limit):
        response = await api_client.post("/api/menus/generate", json=body, headers=headers)
        assert response.status_code == 202

    blocked = await api_client.post("/api/menus/generate", json=body, headers=headers)
    assert blocked.status_code == 429
    assert "重新生成" in blocked.json()["detail"]

    await db_session.rollback()
    regen_total = (
        await db_session.execute(
            select(func.count(MenuGenerationTask.id)).where(
                MenuGenerationTask.is_regeneration.is_(True)
            )
        )
    ).scalar_one()
    assert regen_total == limit


async def test_regeneration_does_not_consume_first_generation_quota(
    api_client, db_session, auth_headers
):
    """重生成不占用首次生成额度: 换过菜单之后, 开新周菜单仍有完整 3 次"""
    user = await make_user(db_session, open_id="ou_quota_split")
    await db_session.commit()
    headers = auth_headers(user.id)

    for _ in range(3):
        response = await api_client.post(
            "/api/menus/generate",
            json={"week_start": "2026-01-05", "force": True},
            headers=headers,
        )
        assert response.status_code == 202

    # 首次生成额度应该是满的 (3 次)
    first_week = await api_client.post(
        "/api/menus/generate", json={"week_start": "2026-01-12"}, headers=headers
    )
    assert first_week.status_code == 202
    other_week = await api_client.post(
        "/api/menus/generate", json={"week_start": "2026-01-19"}, headers=headers
    )
    assert other_week.status_code == 202


async def test_generate_without_login_is_401(api_client, db_session):
    response = await api_client.post("/api/menus/generate", json={"force": True})
    assert response.status_code == 401


async def test_force_generate_reuses_existing_draft(api_client, db_session, auth_headers):
    """无 force 时同一周已有 draft 直接复用, 不再消耗额度"""
    user = await make_user(db_session, open_id="ou_reuse")
    week_start = date(2026, 1, 5)
    menu = Menu(user_id=user.id, week_start_date=week_start, status=MenuStatus.DRAFT)
    db_session.add(menu)
    await db_session.commit()
    headers = auth_headers(user.id)

    response = await api_client.post(
        "/api/menus/generate", json={"week_start": str(week_start)}, headers=headers
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["reused"] is True
    assert payload["menu_id"] == menu.id
    assert payload["task_id"] is None

    await db_session.rollback()
    tasks = (await db_session.execute(select(func.count(MenuGenerationTask.id)))).scalar_one()
    assert tasks == 0
