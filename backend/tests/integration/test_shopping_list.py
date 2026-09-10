"""集成测试: 采购清单差集"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.ingredient import Ingredient
from app.models.recipe import Recipe, RecipeIngredient
from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_menu, make_recipe, make_stock, make_user, week_start_of

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


async def _add_ingredient(db, recipe: Recipe, ingredient: Ingredient, quantity: float, unit: str) -> None:
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=unit,
            amount_text=f"{quantity:g}{unit}",
        )
    )
    await db.flush()


async def _seed(db, open_id: str):
    """两天菜单共用番茄, 番茄炒蛋另需 4 个鸡蛋"""
    user = await make_user(db, open_id=open_id)
    tomato = await make_ingredient(db, "番茄", unit="g", price=0.02)
    egg = await make_ingredient(db, "鸡蛋", unit="个", price=1.5)

    scrambled = await make_recipe(db, "番茄炒蛋", tomato, 300.0, unit="g")
    await _add_ingredient(db, scrambled, egg, 4.0, "个")
    soup = await make_recipe(db, "番茄蛋汤", tomato, 200.0, unit="g")

    menu = await make_menu(
        db, user.id, {0: [(scrambled, "dinner")], 1: [(soup, "dinner")]}, week_start=WEEK_START
    )
    return user.id, menu.id, tomato, egg


async def test_shopping_list_computes_deficit(api_client, db_session, auth_headers):
    user_id, menu_id, tomato, egg = await _seed(db_session, "ou_shop_1")
    await make_stock(db_session, user_id, tomato, 200.0, unit="g")
    await make_stock(db_session, user_id, egg, 6.0, unit="个")
    await db_session.commit()

    response = await api_client.get(
        f"/api/menus/{menu_id}/shopping-list", headers=auth_headers(user_id)
    )
    assert response.status_code == 200
    data = response.json()["data"]

    by_name = {item["name"]: item for item in data["items"]}
    assert by_name["番茄"]["required_quantity"] == 500.0
    assert by_name["番茄"]["in_stock_quantity"] == 200.0
    assert by_name["番茄"]["deficit"] == 300.0
    assert by_name["番茄"]["have_enough"] is False
    assert by_name["鸡蛋"]["required_quantity"] == 4.0
    assert by_name["鸡蛋"]["have_enough"] is True
    assert data["summary"]["to_buy_count"] == 1
    assert data["summary"]["have_count"] == 1

    to_buy = [item["name"] for item in data["items"] if not item["have_enough"]]
    assert to_buy == ["番茄"]


async def test_shopping_list_empty_when_stock_sufficient(api_client, db_session, auth_headers):
    user_id, menu_id, tomato, egg = await _seed(db_session, "ou_shop_2")
    await make_stock(db_session, user_id, tomato, 1000.0, unit="g")
    await make_stock(db_session, user_id, egg, 10.0, unit="个")
    await db_session.commit()

    data = (
        await api_client.get(
            f"/api/menus/{menu_id}/shopping-list", headers=auth_headers(user_id)
        )
    ).json()["data"]
    assert data["summary"]["to_buy_count"] == 0
    assert all(item["have_enough"] for item in data["items"])


async def test_shopping_list_converts_matching_units(api_client, db_session, auth_headers):
    """库存以 kg 记录, 需求以 g 记录, 应换算后相减"""
    user_id, menu_id, tomato, _ = await _seed(db_session, "ou_shop_3")
    await make_stock(db_session, user_id, tomato, 1.0, unit="kg")
    await db_session.commit()

    data = (
        await api_client.get(
            f"/api/menus/{menu_id}/shopping-list", headers=auth_headers(user_id)
        )
    ).json()["data"]
    entry = {item["name"]: item for item in data["items"]}["番茄"]
    assert entry["in_stock_quantity"] == 1000.0
    assert entry["have_enough"] is True


async def test_incompatible_units_are_flagged(api_client, db_session, auth_headers):
    """库存单位与需求单位无法换算时, 标记 unit_mismatch 而不是当成 0"""
    user_id, menu_id, tomato, _ = await _seed(db_session, "ou_shop_5")
    await make_stock(db_session, user_id, tomato, 2.0, unit="袋")
    await db_session.commit()

    data = (
        await api_client.get(
            f"/api/menus/{menu_id}/shopping-list", headers=auth_headers(user_id)
        )
    ).json()["data"]
    entry = {item["name"]: item for item in data["items"]}["番茄"]
    assert entry["unit_mismatch"] is True
    assert entry["in_stock_quantity"] == 0.0
    assert entry["have_enough"] is False


async def test_unquantified_amount_reported_without_guessing(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_shop_4")
    salt = await make_ingredient(db_session, "盐", unit="g", price=0.003)
    recipe = await make_recipe(db_session, "清炒时蔬", salt, 2.0, unit="g")
    row = (
        await db_session.execute(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
        )
    ).scalar_one()
    row.quantity = None
    row.amount_text = "适量"
    menu = await make_menu(db_session, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    user_id, menu_id = user.id, menu.id
    await db_session.commit()

    data = (
        await api_client.get(
            f"/api/menus/{menu_id}/shopping-list", headers=auth_headers(user_id)
        )
    ).json()["data"]
    entry = data["items"][0]
    assert entry["name"] == "盐"
    assert entry["required_quantity"] is None
    assert entry["deficit"] is None
    assert entry["have_enough"] is False
    assert data["summary"]["to_buy_count"] == 1
