"""集成测试: 撤销「标记已做」-> 库存还原 + 消耗流水删除

误触是高频错误, 所以标记后给 6 秒后悔窗口。撤销必须是**真的**撤销:
批次行还在就加回原行, 已经被扣空删掉的要按流水里的食材/单位重建一行。
"""
from __future__ import annotations

from datetime import date

from app.models.fridge_inventory import ConsumptionRecord, FridgeInventory
from app.models.menu import MenuItem
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_menu, make_recipe, make_stock, make_user, week_start_of

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


async def _prepare(db, open_id: str, name: str, needed: float, stock: float):
    user = await make_user(db, open_id=open_id)
    ingredient = await make_ingredient(db, f"{name}食材", unit="g", price=0.02)
    recipe = await make_recipe(db, name, ingredient, needed)
    menu = await make_menu(db, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    await make_stock(db, user.id, ingredient, stock, unit="g")
    return user.id, menu.id, ingredient.id


async def _item_id(db, menu_id: int) -> int:
    db.expire_all()
    await db.rollback()
    result = await db.execute(select(MenuItem).where(MenuItem.menu_id == menu_id))
    return result.scalars().first().id


async def _stock_total(db, ingredient_id: int) -> float:
    await db.rollback()
    rows = (
        await db.execute(
            select(FridgeInventory).where(FridgeInventory.ingredient_id == ingredient_id)
        )
    ).scalars().all()
    return sum(row.quantity for row in rows)


async def test_undo_restores_partially_consumed_batch(api_client, db_session, auth_headers):
    """批次行还剩一些: 直接加回原行, 不新建"""
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_undo_1", "番茄炒蛋", needed=200.0, stock=500.0
    )
    await db_session.commit()
    item_id = await _item_id(db_session, menu_id)

    cooked = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert cooked.status_code == 200
    assert await _stock_total(db_session, ingredient_id) == 300.0

    undo = await api_client.delete(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert undo.status_code == 200
    data = undo.json()["data"]
    assert len(data["restored"]) == 1
    assert data["skipped"] == 0

    assert await _stock_total(db_session, ingredient_id) == 500.0

    await db_session.rollback()
    records = (await db_session.execute(select(ConsumptionRecord))).scalars().all()
    assert records == []


async def test_undo_recreates_deleted_batch(api_client, db_session, auth_headers):
    """批次行被扣空后会被删除, 撤销要按流水里的食材/单位补一行回来"""
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_undo_2", "清炒时蔬", needed=300.0, stock=300.0
    )
    await db_session.commit()
    item_id = await _item_id(db_session, menu_id)

    await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    # 刚好扣完, 批次行应该没了
    assert await _stock_total(db_session, ingredient_id) == 0.0

    undo = await api_client.delete(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert undo.status_code == 200
    assert undo.json()["data"]["restored"][0]["quantity"] == 300.0
    # 单位要从流水里带回来, 不能丢
    assert undo.json()["data"]["restored"][0]["unit"] == "g"
    assert await _stock_total(db_session, ingredient_id) == 300.0


async def test_undo_clears_cooked_flag_and_allows_re_cook(api_client, db_session, auth_headers):
    """撤销后可以再次标记已做, 而且会重新扣一次"""
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_undo_3", "红烧肉", needed=100.0, stock=500.0
    )
    await db_session.commit()
    item_id = await _item_id(db_session, menu_id)

    first = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert first.json()["data"]["already_cooked"] is False
    await api_client.delete(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    second = await api_client.put(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert second.json()["data"]["already_cooked"] is False
    assert len(second.json()["data"]["consumed"]) == 1


async def test_undo_is_idempotent(api_client, db_session, auth_headers):
    """没标记过就撤销: 不报错, 库存也不动"""
    user_id, menu_id, ingredient_id = await _prepare(
        db_session, "ou_undo_4", "凉拌黄瓜", needed=100.0, stock=400.0
    )
    await db_session.commit()
    item_id = await _item_id(db_session, menu_id)

    undo = await api_client.delete(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(user_id)
    )
    assert undo.status_code == 200
    assert undo.json()["data"]["restored"] == []
    assert await _stock_total(db_session, ingredient_id) == 400.0


async def test_undo_another_users_item_is_404(api_client, db_session, auth_headers):
    """越权撤销统一 404 (不是 403, 不然等于告诉对方"这个 id 存在")"""
    _owner_id, menu_id, _ = await _prepare(
        db_session, "ou_undo_owner", "土豆丝", needed=100.0, stock=300.0
    )
    intruder = await make_user(db_session, open_id="ou_undo_intruder")
    intruder_id = intruder.id
    await db_session.commit()
    item_id = await _item_id(db_session, menu_id)

    response = await api_client.delete(
        f"/api/menus/{menu_id}/items/{item_id}/cooked", headers=auth_headers(intruder_id)
    )
    assert response.status_code == 404
