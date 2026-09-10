"""集成测试: 菜单编辑 (换菜/锁定/确认) 与重生成保护"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from sqlalchemy import select

from app.llm.base import LLMClient
from app.models.menu import Menu, MenuItem, MenuStatus
from app.models.recipe import Recipe
from app.services.generation_service import MenuGenerationPipeline
from tests.conftest import requires_mysql
from tests.factories import (
    make_ingredient,
    make_menu,
    make_preferences,
    make_recipe,
    make_user,
    week_start_of,
)

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


class FakeLLM(LLMClient):
    def __init__(self, payload: Dict[str, Any]):
        super().__init__("fake")
        self.payload = payload

    async def chat(self, messages, temperature=0.7, max_tokens=4000) -> str:
        import json

        return json.dumps(self.payload, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True


def _week_payload(recipes: List[Dict[str, Any]]) -> Dict[str, Any]:
    days = []
    for offset, recipe in enumerate(recipes):
        days.append(
            {
                "date": str(WEEK_START + timedelta(days=offset)),
                "day_type": "weekday",
                "meals": {"dinner": {"recipes": [recipe]}},
            }
        )
    return {"week_menu": days}


def _recipe(name: str, ingredient: str = "青菜") -> Dict[str, Any]:
    return {
        "name": name,
        "ingredients": [{"name": ingredient, "quantity": "200g", "unit": ""}],
        "calories": 400,
        "protein_g": 25.0,
        "carb_g": 40.0,
        "fat_g": 12.0,
        "cook_minutes": 20,
        "steps": "炒熟",
    }


async def _items(db, menu_id: int) -> List[MenuItem]:
    """重新开启事务读取最新数据 (生成流程使用独立 session)"""
    await db.rollback()
    result = await db.execute(
        select(MenuItem)
        .where(MenuItem.menu_id == menu_id)
        .order_by(MenuItem.meal_date, MenuItem.id)
    )
    return list(result.scalars().all())


async def test_replace_item_swaps_recipe(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_edit_1")
    ingredient = await make_ingredient(db_session, "土豆", price=0.01)
    recipe = await make_recipe(db_session, "醋溜土豆丝", ingredient, 200)
    menu = await make_menu(db_session, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    user_id, menu_id, original_recipe_id = user.id, menu.id, recipe.id
    await db_session.commit()

    item_id = (await _items(db_session, menu_id))[0].id
    headers = auth_headers(user_id)

    response = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/replace",
        json={
            "recipe_name": "干锅花菜",
            "recipe_ingredients": [{"name": "花菜", "quantity": "300g", "unit": ""}],
            "calories": 300,
            "cook_minutes": 15,
            "steps": "爆炒",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["days"][0]["meals"][0]["recipe"]["name"] == "干锅花菜"

    items = await _items(db_session, menu_id)
    assert len(items) == 1
    assert items[0].recipe_id != original_recipe_id


async def test_lock_unlock_and_confirm(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_edit_2")
    ingredient = await make_ingredient(db_session, "排骨", price=0.05)
    recipe = await make_recipe(db_session, "红烧排骨", ingredient, 500)
    menu = await make_menu(db_session, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    user_id, menu_id = user.id, menu.id
    await db_session.commit()

    item_id = (await _items(db_session, menu_id))[0].id
    headers = auth_headers(user_id)

    locked = await api_client.put(f"/api/menus/{menu_id}/items/{item_id}/lock", headers=headers)
    assert locked.status_code == 200
    assert locked.json()["data"]["is_locked"] is True

    unlocked = await api_client.put(f"/api/menus/{menu_id}/items/{item_id}/unlock", headers=headers)
    assert unlocked.json()["data"]["is_locked"] is False

    confirmed = await api_client.post(f"/api/menus/{menu_id}/confirm", headers=headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == MenuStatus.CONFIRMED

    stored = (await _items(db_session, menu_id))[0]
    assert stored.is_locked is False
    stored_menu = (
        await db_session.execute(select(Menu).where(Menu.id == menu_id))
    ).scalar_one()
    assert stored_menu.status == MenuStatus.CONFIRMED


async def test_locked_item_survives_regeneration(db_session):
    user = await make_user(db_session, open_id="ou_edit_3")
    await make_preferences(db_session, user.id)
    ingredient = await make_ingredient(db_session, "食材", price=0.01)
    locked_recipe = await make_recipe(db_session, "老妈蹄花", ingredient, 400)
    other_recipe = await make_recipe(db_session, "清蒸鲈鱼", ingredient, 400)
    menu = await make_menu(
        db_session,
        user.id,
        {0: [(locked_recipe, "dinner")], 1: [(other_recipe, "dinner")]},
        week_start=WEEK_START,
    )
    user_id, menu_id = user.id, menu.id
    items = await _items(db_session, menu_id)
    first_day_item_id = items[0].id
    items[0].is_locked = True
    await db_session.commit()

    await MenuGenerationPipeline(FakeLLM(_week_payload([_recipe("新菜A"), _recipe("新菜B")]))).run(
        user_id, WEEK_START
    )

    after = await _items(db_session, menu_id)
    by_id = {item.id: item for item in after}
    assert first_day_item_id in by_id, "锁定餐次不应被删除"
    assert len(after) == 2

    recipe_ids = {item.meal_date: item.recipe_id for item in after}
    rows = await db_session.execute(
        select(Recipe.id, Recipe.name).where(Recipe.id.in_(list(recipe_ids.values())))
    )
    name_by_id = {row[0]: row[1] for row in rows.all()}
    assert name_by_id[recipe_ids[WEEK_START]] == "老妈蹄花"
    assert name_by_id[recipe_ids[WEEK_START + timedelta(days=1)]] == "新菜B"


async def test_confirm_then_generate_still_reuses(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_edit_4")
    menu = Menu(user_id=user.id, week_start_date=WEEK_START, status=MenuStatus.CONFIRMED)
    db_session.add(menu)
    user_id, menu_id = user.id, menu.id
    await db_session.commit()

    response = await api_client.post(
        "/api/menus/generate", json={"week_start": str(WEEK_START)}, headers=auth_headers(user_id)
    )
    assert response.status_code == 200
    assert response.json()["data"]["menu_id"] == menu_id


async def test_cross_user_menu_access_is_404(api_client, db_session, auth_headers):
    owner = await make_user(db_session, open_id="ou_owner")
    intruder = await make_user(db_session, open_id="ou_intruder")
    ingredient = await make_ingredient(db_session, "豆腐", price=0.01)
    recipe = await make_recipe(db_session, "麻婆豆腐", ingredient, 300)
    menu = await make_menu(db_session, owner.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    menu_id = menu.id
    intruder_id = intruder.id
    await db_session.commit()

    item_id = (await _items(db_session, menu_id))[0].id
    headers = auth_headers(intruder_id)

    assert (await api_client.get(f"/api/menus/{menu_id}", headers=headers)).status_code == 404
    assert (
        await api_client.post(f"/api/menus/{menu_id}/confirm", headers=headers)
    ).status_code == 404
    assert (
        await api_client.get(f"/api/menus/{menu_id}/shopping-list", headers=headers)
    ).status_code == 404
    assert (
        await api_client.put(f"/api/menus/{menu_id}/items/{item_id}/lock", headers=headers)
    ).status_code == 404
