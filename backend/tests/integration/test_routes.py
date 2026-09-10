"""集成测试: 认证矩阵、偏好空值与多用户数据隔离"""
from __future__ import annotations

import pytest

from tests.conftest import requires_mysql
from tests.factories import (
    make_ingredient,
    make_menu,
    make_recipe,
    make_stock,
    make_user,
    week_start_of,
)
from datetime import date

pytestmark = requires_mysql

PROTECTED_ENDPOINTS = [
    ("GET", "/api/auth/me"),
    ("GET", "/api/preferences/household"),
    ("GET", "/api/preferences/summary"),
    ("GET", "/api/menus/current"),
    ("GET", "/api/menus/1"),
    ("GET", "/api/menus/1/shopping-list"),
    ("GET", "/api/inventory"),
    ("GET", "/api/inventory/expiring"),
    ("GET", "/api/products"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
async def test_anonymous_requests_are_401(api_client, db_session, method, path):
    response = await api_client.request(method, path)
    assert response.status_code == 401
    assert response.json()["detail"]


async def test_health_reports_database_ok(api_client, db_session):
    response = await api_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_preferences_return_null_when_unset(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_pref_1")
    user_id = user.id
    await db_session.commit()
    headers = auth_headers(user_id)

    for path in (
        "/api/preferences/household",
        "/api/preferences/diet",
        "/api/preferences/allergy",
        "/api/preferences/health-goal",
        "/api/preferences/budget",
    ):
        response = await api_client.get(path, headers=headers)
        assert response.status_code == 200, path
        assert response.json()["data"] is None, path


async def test_household_equipments_roundtrip_as_list(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_pref_2")
    user_id = user.id
    await db_session.commit()
    headers = auth_headers(user_id)

    saved = await api_client.put(
        "/api/preferences/household",
        json={
            "member_count": 4,
            "meals_per_day": 3,
            "kitchen_equipments": ["灶台", "空气炸锅"],
            "weekday_cook_minutes": 25,
            "weekend_cook_minutes": 60,
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["kitchen_equipments"] == ["灶台", "空气炸锅"]

    fetched = await api_client.get("/api/preferences/household", headers=headers)
    assert fetched.json()["data"]["kitchen_equipments"] == ["灶台", "空气炸锅"]
    assert isinstance(fetched.json()["data"]["kitchen_equipments"], list)


async def test_preferences_are_isolated_per_user(api_client, db_session, auth_headers):
    first = await make_user(db_session, open_id="ou_pref_a")
    second = await make_user(db_session, open_id="ou_pref_b")
    first_id, second_id = first.id, second.id
    await db_session.commit()

    await api_client.put(
        "/api/preferences/household",
        json={"member_count": 5, "meals_per_day": 2, "kitchen_equipments": ["蒸锅"]},
        headers=auth_headers(first_id),
    )

    other = await api_client.get("/api/preferences/household", headers=auth_headers(second_id))
    assert other.json()["data"] is None


async def test_inventory_is_isolated_per_user(api_client, db_session, auth_headers):
    owner = await make_user(db_session, open_id="ou_stock_a")
    other = await make_user(db_session, open_id="ou_stock_b")
    owner_id, other_id = owner.id, other.id
    ingredient = await make_ingredient(db_session, "菠菜", unit="g")
    await make_stock(db_session, owner_id, ingredient, 300.0, unit="g")
    await db_session.commit()

    mine = await api_client.get("/api/inventory", headers=auth_headers(owner_id))
    theirs = await api_client.get("/api/inventory", headers=auth_headers(other_id))

    assert len(mine.json()["data"]) == 1
    assert theirs.json()["data"] == []


async def test_current_menu_returns_full_structure(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_current")
    ingredient = await make_ingredient(db_session, "牛肉", unit="g", price=0.06)
    recipe = await make_recipe(db_session, "小炒牛肉", ingredient, 200.0)
    menu = await make_menu(
        db_session, user.id, {0: [(recipe, "dinner")]}, week_start=week_start_of(date(2026, 1, 5))
    )
    user_id, menu_id = user.id, menu.id
    await db_session.commit()

    response = await api_client.get("/api/menus/current", headers=auth_headers(user_id))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == menu_id
    assert data["totals"]["meal_count"] == 1
    assert data["days"][0]["meals"][0]["recipe"]["name"] == "小炒牛肉"
    assert data["days"][0]["meals"][0]["recipe"]["ingredients"][0]["name"] == "牛肉"
    assert data["nutrition"]["days_count"] == 1


async def test_current_menu_404_when_empty(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_no_menu")
    user_id = user.id
    await db_session.commit()
    response = await api_client.get("/api/menus/current", headers=auth_headers(user_id))
    assert response.status_code == 404


async def test_unknown_generation_task_is_404(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_task_404")
    user_id = user.id
    await db_session.commit()
    response = await api_client.get("/api/menus/generation-tasks/999", headers=auth_headers(user_id))
    assert response.status_code == 404
