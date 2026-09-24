"""集成测试: 按冰箱重排本周

验收三件事:
  1. 冰箱里有的食材 -> 那道菜优先排进来 (SCORE_STOCK 是主导权重)
  2. 锁定的餐次原封不动
  3. 本周没有菜单时明确报错, 而不是静默成功
"""
from __future__ import annotations

from datetime import date

import pytest
from app.models.menu import Menu
from app.services.fridge_menu_service import FridgeMenuError, FridgeMenuService
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.conftest import requires_mysql
from tests.factories import (
    make_ingredient,
    make_menu,
    make_preferences,
    make_recipe,
    make_stock,
    make_user,
    week_start_of,
)

pytestmark = requires_mysql

WEEK_START = week_start_of(date(2026, 1, 5))


async def _reload(db_session, menu_id: int) -> Menu:
    result = await db_session.execute(
        select(Menu).options(selectinload(Menu.menu_items)).where(Menu.id == menu_id)
    )
    return result.scalar_one()


async def test_rebuild_prefers_dish_covered_by_fridge(db_session):
    user = await make_user(db_session, open_id="ou_fridge_rebuild")
    await make_preferences(db_session, user.id)

    cabbage = await make_ingredient(db_session, "白菜")
    tofu = await make_ingredient(db_session, "豆腐")
    # 冰箱里只有白菜
    await make_stock(db_session, user.id, cabbage, 500)

    with_cabbage = await make_recipe(db_session, "醋溜白菜", cabbage, 200, calories=300)
    with_tofu = await make_recipe(db_session, "麻婆豆腐", tofu, 200, calories=300)
    starter = await make_recipe(db_session, "清炒时蔬", cabbage, 150, calories=350)

    menu = await make_menu(
        db_session,
        user.id,
        {0: [(with_tofu, "dinner")], 1: [(starter, "dinner")]},
        week_start=WEEK_START,
    )
    await db_session.commit()

    # commit 会让 ORM 对象过期: 先 reload 再动关系, 否则会以同步方式发 IO
    menu = await _reload(db_session, menu.id)
    items = sorted(menu.menu_items, key=lambda row: row.meal_date)
    free_item_id = items[0].id
    locked_item_id = items[1].id
    # 第二天这餐锁住 —— 重排必须绕开它
    items[1].is_locked = True
    await db_session.commit()

    menu_id = menu.id

    result = await FridgeMenuService(db_session).rebuild(user.id, str(WEEK_START))
    await db_session.commit()

    assert result.locked_items == 1
    assert result.changed_items == 1
    assert result.cookable_now >= 1

    menu = await _reload(db_session, menu_id)
    by_id = {row.id: row for row in menu.menu_items}

    # 未锁定的那一餐: 从"豆腐(冰箱没有)"换成了"白菜(冰箱有)"
    assert by_id[free_item_id].recipe_id == with_cabbage.id
    # 锁定的那一餐一动不动
    assert by_id[locked_item_id].is_locked
    assert by_id[locked_item_id].recipe_id == starter.id


async def test_rebuild_without_menu_raises(db_session):
    user = await make_user(db_session, open_id="ou_fridge_no_menu")
    await make_preferences(db_session, user.id)

    with pytest.raises(FridgeMenuError) as excinfo:
        await FridgeMenuService(db_session).rebuild(user.id, str(WEEK_START))

    assert "先生成" in str(excinfo.value)
