"""集成测试: 今日页聚合接口

这页最容易出的两类问题:
  * 没填偏好/没生成菜单时直接 500 —— 空状态是正常状态, 必须 200
  * 补单卡片算的是"整周缺口"而不是"今晚缺口" —— 会把用户吓一跳
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import (
    make_ingredient,
    make_menu,
    make_preferences,
    make_recipe,
    make_stock,
    make_user,
)

pytestmark = requires_mysql


def _at(hour: int, minute: int = 0) -> datetime:
    """用真实日期 + 指定时刻构造 now

    注意不能随便换日期: "今天"决定了要取菜单里的哪一天, 日期一换就取不到餐次了。
    """
    return datetime.combine(date.today(), time(hour, minute))


def _today_offset() -> int:
    return (date.today() - (date.today() - timedelta(days=date.today().weekday()))).days


async def _seed_menu(db, open_id: str, *, stock_tomato: float = 0.0):
    user = await make_user(db, open_id=open_id)
    await make_preferences(db, user.id)
    tomato = await make_ingredient(db, "番茄", unit="g", price=0.02)
    egg = await make_ingredient(db, "鸡蛋", unit="个", price=1.5)
    recipe = await make_recipe(db, "番茄炒蛋", tomato, 500.0, unit="g", calories=520, protein_g=42)
    from app.models.recipe import RecipeIngredient

    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=egg.id,
            quantity=4.0,
            unit="个",
            amount_text="4个",
        )
    )
    await db.flush()

    week_start = date.today() - timedelta(days=date.today().weekday())
    menu = await make_menu(db, user.id, {_today_offset(): [(recipe, "dinner")]}, week_start=week_start)
    if stock_tomato:
        await make_stock(db, user.id, tomato, stock_tomato, unit="g")
    return user.id, menu.id, tomato, egg


async def test_today_carries_layout_version_and_home_fields(api_client, db_session, auth_headers):
    """/api/today 是首页唯一数据源, 灰度字段和首页依赖的字段命名都不能漂

    layout_version 在这里比在 /api/decide 更关键: 用户进首页打的第一个 home_view
    是**这个响应之后**才打的, 这里拿不到灰度值, 丢的正是最该归因的那一段。
    """
    user = await make_user(db_session, open_id="ou_today_layout")
    await db_session.commit()

    data = (await api_client.get("/api/today", headers=auth_headers(user.id))).json()["data"]

    # R-16: 服务端没配就是 null, 不许兜底成 'v1.2'(否则"不知道在哪组"会被算进组)
    assert "layout_version" in data
    assert data["layout_version"] is None
    # 首页三段式直接读的这几个字段, 改名 = 首页静默丢模块
    for key in ("tonight", "takeout", "expiring", "timeline", "budget", "ready"):
        assert key in data, f"/api/today 少了 {key}, 首页会静默丢一个模块"


async def test_today_returns_empty_state_without_menu(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_today_empty")
    await db_session.commit()

    response = await api_client.get("/api/today", headers=auth_headers(user.id))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready"] == {"has_preferences": False, "has_menu": False}
    assert data["meals"] == []
    assert data["tonight"] is None
    assert data["order"] is None
    assert [entry["key"] for entry in data["timeline"]] == ["menu_push", "stock_check", "cook_deduct"]
    # 定时推送默认关闭 -> 如实说未开启, 而不是假装已送达
    assert data["timeline"][0]["status"] == "skipped"
    assert data["timeline"][0]["detail"] == "定时推送未开启"


async def test_today_returns_full_shape_with_menu(api_client, db_session, auth_headers):
    user_id, menu_id, _tomato, _egg = await _seed_menu(db_session, "ou_today_full")
    await db_session.commit()

    response = await api_client.get("/api/today", headers=auth_headers(user_id))
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["ready"] == {"has_preferences": True, "has_menu": True}
    assert data["menu_id"] == menu_id
    assert data["week"]["week_start_date"] == str(date.today() - timedelta(days=date.today().weekday()))
    assert data["budget"]["daily_budget"] == 35.0
    assert data["budget"]["takeout_reference_price"] == 26.0
    assert data["nutrition"]["target_calories"] == 1800

    assert len(data["meals"]) == 1
    tonight = data["tonight"]
    assert tonight["name"] == "番茄炒蛋"
    assert tonight["calories"] == 520
    assert tonight["servings"] == 3
    assert tonight["meal_type"] == "dinner"
    assert tonight["takeout"]["recommended"] == "homemade"
    assert tonight["takeout"]["takeout"]["cost"] == 26.0
    assert tonight["takeout"]["homemade"]["cost"] == tonight["estimated_cost"]
    assert [item["name"] for item in tonight["ingredients"]] == ["番茄", "鸡蛋"]

    # 顶层的 takeout 必须和今晚那份是同一个结论: 今日页的"自做 vs 外卖"卡读的是它,
    # 之前这里一直是 None, 卡片就永远不显示。
    assert data["takeout"] is not None
    assert data["takeout"]["recommended"] == tonight["takeout"]["recommended"]
    assert data["takeout"]["link"]


async def test_today_meal_is_empty_on_a_day_without_meals(api_client, db_session, auth_headers):
    """菜单只排了明天 -> 今天没有餐次, 但整周数据照常返回"""
    user = await make_user(db_session, open_id="ou_today_nomeal")
    await make_preferences(db_session, user.id)
    tomato = await make_ingredient(db_session, "番茄", unit="g", price=0.02)
    recipe = await make_recipe(db_session, "番茄炒蛋", tomato, 200.0, unit="g")
    week_start = date.today() - timedelta(days=date.today().weekday())
    await make_menu(db_session, user.id, {_today_offset() + 1: [(recipe, "dinner")]}, week_start=week_start)
    await db_session.commit()

    data = (await api_client.get("/api/today", headers=auth_headers(user.id))).json()["data"]
    assert data["ready"]["has_menu"] is True
    assert data["meals"] == []
    assert data["tonight"] is None
    assert data["week"]["totals"]["meal_count"] == 1


async def test_today_is_isolated_per_user(api_client, db_session, auth_headers):
    await _seed_menu(db_session, "ou_today_a")
    other = await make_user(db_session, open_id="ou_today_b")
    await db_session.commit()

    data = (await api_client.get("/api/today", headers=auth_headers(other.id))).json()["data"]
    assert data["ready"]["has_menu"] is False
    assert data["menu_id"] is None


async def test_order_card_uses_only_tonights_ingredients(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_today_scope")
    await make_preferences(db_session, user.id)
    tomato = await make_ingredient(db_session, "番茄", unit="g", price=0.02)
    beef = await make_ingredient(db_session, "牛腩", unit="g", price=0.08)

    tonight_recipe = await make_recipe(db_session, "番茄炒蛋", tomato, 500.0, unit="g")
    later_recipe = await make_recipe(db_session, "炖牛腩", beef, 1000.0, unit="g")
    week_start = date.today() - timedelta(days=date.today().weekday())
    await make_menu(
        db_session,
        user.id,
        {_today_offset(): [(tonight_recipe, "dinner")], _today_offset() + 3: [(later_recipe, "dinner")]},
        week_start=week_start,
    )
    await db_session.commit()

    data = (await api_client.get("/api/today", headers=auth_headers(user.id))).json()["data"]
    order = data["order"]
    assert order is not None
    primary = [line["name"] for line in order["items"] if not line["is_topup"]]
    assert primary == ["番茄"]  # 牛腩是后天的, 不塞进今晚的主清单
    assert order["missing_count"] == 1
    assert data["shopping"]["to_buy_count"] == 2


async def test_takeout_price_endpoint_remembers_the_new_price(api_client, db_session, auth_headers):
    user_id, _menu_id, _tomato, _egg = await _seed_menu(db_session, "ou_today_price")
    await db_session.commit()

    response = await api_client.post(
        "/api/today/takeout-price", json={"price": 31}, headers=auth_headers(user_id)
    )
    assert response.status_code == 200
    assert response.json()["data"]["takeout_reference_price"] == 31.0

    data = (await api_client.get("/api/today", headers=auth_headers(user_id))).json()["data"]
    assert data["budget"]["takeout_reference_price"] == 31.0
    assert data["tonight"]["takeout"]["takeout"]["cost"] == 31.0
    assert data["tonight"]["takeout"]["saving"] == round(
        31.0 - data["tonight"]["estimated_cost"], 2
    )


async def test_takeout_price_rejects_garbage(api_client, db_session, auth_headers):
    user_id, _menu_id, _t, _e = await _seed_menu(db_session, "ou_today_price_bad")
    await db_session.commit()

    bad = await api_client.post(
        "/api/today/takeout-price", json={"price": "很贵"}, headers=auth_headers(user_id)
    )
    assert bad.status_code == 422
    too_big = await api_client.post(
        "/api/today/takeout-price", json={"price": 9999}, headers=auth_headers(user_id)
    )
    assert too_big.status_code == 422


async def test_takeout_price_without_budget_is_404(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_today_nobudget")
    await db_session.commit()
    response = await api_client.post(
        "/api/today/takeout-price", json={"price": 25}, headers=auth_headers(user.id)
    )
    assert response.status_code == 404


async def test_timeline_stock_check_waits_until_evening(db_session):
    """时间线要随"现在几点"变化: 17:30 之前是待触发, 之后算已检查"""
    from app.services.today_service import TodayService

    user_id, _menu_id, _t, _e = await _seed_menu(db_session, "ou_today_timeline")
    await db_session.commit()

    morning = await TodayService(db_session).build(user_id, now=_at(9, 0))
    evening = await TodayService(db_session).build(user_id, now=_at(18, 0))
    assert morning["timeline"][1]["status"] == "pending"
    assert evening["timeline"][1]["status"] == "sent"
    assert "缺" in evening["timeline"][1]["detail"]


async def test_timeline_cook_entry_flips_after_marking_cooked(db_session):
    from app.models.menu import MenuItem
    from app.services.today_service import TodayService

    user_id, menu_id, _t, _e = await _seed_menu(db_session, "ou_today_cook")
    await db_session.commit()

    before = await TodayService(db_session).build(user_id, now=_at(20, 0))
    assert before["timeline"][2]["status"] == "pending"

    item = (
        await db_session.execute(select(MenuItem).where(MenuItem.menu_id == menu_id))
    ).scalar_one()
    item.is_cooked = True
    await db_session.flush()

    after = await TodayService(db_session).build(user_id, now=_at(20, 0))
    assert after["timeline"][2]["status"] == "sent"
    assert "已扣减" in after["timeline"][2]["detail"]


async def test_expiring_ingredient_used_tonight_is_flagged(db_session):
    from app.services.today_service import TodayService

    user_id, _menu_id, tomato, _egg = await _seed_menu(db_session, "ou_today_expiring")
    await make_stock(
        db_session,
        user_id,
        tomato,
        100.0,
        unit="g",
        expiry=date.today() + timedelta(days=1),
    )
    await db_session.commit()

    data = await TodayService(db_session).build(user_id, now=_at(20, 0))
    assert len(data["expiring"]) == 1
    assert data["expiring"][0]["ingredient_name"] == "番茄"
    assert data["expiring"][0]["used_tonight"] is True
    assert data["tonight"]["uses_expiring"][0]["ingredient_name"] == "番茄"
