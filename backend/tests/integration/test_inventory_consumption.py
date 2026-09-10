"""集成测试: 标记已做 -> 库存扣减 -> 消耗记录"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models.fridge_inventory import ConsumptionRecord, FridgeInventory
from app.models.menu import MenuItem
from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_menu, make_recipe, make_stock, make_user, week_start_of

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


async def _prepare(db, open_id: str, recipe_name: str, needed: float, stock: float, expiry=None):
    user = await make_user(db, open_id=open_id)
    ingredient = await make_ingredient(db, f"{recipe_name}食材", unit="g", price=0.02)
    recipe = await make_recipe(db, recipe_name, ingredient, needed)
    menu = await make_menu(db, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    await make_stock(db, user.id, ingredient, stock, unit="g", expiry=expiry)
    return user.id, menu.id, ingredient.id


async def _first_item_id(db, menu_id: int) -> int:
    await db.rollback()
    result = await db.execute(select(MenuItem).where(MenuItem.menu_id == menu_id))
    return result.scalars().first().id


async def test_cooked_reduces_inventory_and_records_consumption(
    api_client, db_session, auth_headers
):
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_inv_1", "番茄炒蛋", needed=200.0, stock=500.0
    )
    await db_session.commit()
    item_id = await _first_item_id(db_session, menu_id)

    response = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["already_cooked"] is False
    assert payload["missing"] == []
    assert len(payload["consumed"]) == 1

    await db_session.rollback()
    stock_rows = (
        await db_session.execute(
            select(FridgeInventory).where(FridgeInventory.ingredient_id == ingredient_id)
        )
    ).scalars().all()
    assert len(stock_rows) == 1
    assert stock_rows[0].quantity == 300.0

    records = (await db_session.execute(select(ConsumptionRecord))).scalars().all()
    assert len(records) == 1
    assert records[0].quantity == 200.0
    assert records[0].menu_item_id == item_id

    refreshed = (
        await db_session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one()
    assert refreshed.is_cooked is True


async def test_insufficient_stock_does_not_block(api_client, db_session, auth_headers):
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_inv_2", "红烧肉", needed=300.0, stock=120.0
    )
    await db_session.commit()
    item_id = await _first_item_id(db_session, menu_id)

    response = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert len(payload["missing"]) == 1
    assert payload["missing"][0]["deficit"] == 180.0

    await db_session.rollback()
    remaining = (
        await db_session.execute(select(FridgeInventory))
    ).scalars().all()
    assert remaining == []
    assert (await db_session.execute(select(ConsumptionRecord))).scalars().first().quantity == 120.0


async def test_second_cook_is_idempotent(api_client, db_session, auth_headers):
    user_id, menu_id, _ = await _prepare(db_session, "ou_inv_3", "清蒸鱼", needed=100.0, stock=500.0)
    await db_session.commit()
    item_id = await _first_item_id(db_session, menu_id)
    headers = auth_headers(user_id)

    await api_client.put(f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=headers)
    again = await api_client.put(f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=headers)

    assert again.status_code == 200
    assert again.json()["data"]["already_cooked"] is True
    assert again.json()["data"]["consumed"] == []

    await db_session.rollback()
    assert len((await db_session.execute(select(ConsumptionRecord))).scalars().all()) == 1


async def test_expiring_stock_is_consumed_first(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_inv_4")
    ingredient = await make_ingredient(db_session, "牛奶", unit="ml", price=0.01)
    recipe = await make_recipe(db_session, "牛奶炖蛋", ingredient, 200.0, unit="ml")
    menu = await make_menu(db_session, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    user_id, menu_id = user.id, menu.id
    await make_stock(db_session, user.id, ingredient, 150.0, unit="ml", expiry=date.today() + timedelta(days=1))
    await make_stock(db_session, user.id, ingredient, 400.0, unit="ml", expiry=date.today() + timedelta(days=30))
    await db_session.commit()
    item_id = await _first_item_id(db_session, menu_id)

    await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )

    await db_session.rollback()
    rows = (
        await db_session.execute(
            select(FridgeInventory).order_by(FridgeInventory.expiry_date.asc())
        )
    ).scalars().all()
    assert len(rows) == 1, "临期那批应被优先扣完"
    assert rows[0].quantity == 350.0


async def test_cooking_another_users_item_is_404(api_client, db_session, auth_headers):
    _, menu_id, _ = await _prepare(db_session, "ou_inv_5", "青菜", needed=50.0, stock=100.0)
    intruder = await make_user(db_session, open_id="ou_inv_intruder")
    intruder_id = intruder.id
    await db_session.commit()
    item_id = await _first_item_id(db_session, menu_id)

    response = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(intruder_id)
    )
    assert response.status_code == 404
