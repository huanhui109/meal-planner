"""集成测试: 本地优先菜单生成、AI 兜底与来源标注

覆盖 `MenuGenerationPipeline.run` 的三条路径:
  * auto/local: 本地菜谱库拼得够满 -> 不调模型, source=local
  * 本地库不足 -> 把候选短名单交给模型, source=mixed
  * mode=ai   -> 完全跳过本地编排, source=ai
再覆盖「换一道」本地优先, 以及 menu.source 的序列化输出。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from app.llm.base import LLMClient
from app.models.menu import Menu, MenuItem
from app.schemas.recipe import MenuItemReplaceRequest
from app.services.generation_service import MODE_AI, MenuGenerationPipeline
from app.services.menu_service import MenuService
from app.services.replacement_service import ReplacementService
from sqlalchemy import select
from sqlalchemy.orm import selectinload

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
MEALS_PER_DAY = 2
TOTAL_SLOTS = 7 * MEALS_PER_DAY  # 工作日晚餐 + 周末三餐等 -> 这里 household 固定 2 餐/天


class SpyLLM(LLMClient):
    """记录调用次数的替身; 预置一周 JSON 便于 AI 兜底路径"""

    def __init__(self, payload: Dict[str, Any] | None = None, explode: bool = False):
        super().__init__("spy")
        self.payload = payload
        self.explode = explode
        self.calls = 0

    async def chat(self, messages, temperature=0.7, max_tokens=4000) -> str:
        self.calls += 1
        if self.explode:
            raise AssertionError("本地菜谱库已拼齐, 不应调用 LLM")
        import json

        return json.dumps(self.payload or {"week_menu": []}, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True


def _dish(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "ingredients": [{"name": "白菜", "quantity": "100g", "unit": ""}],
        "calories": 300,
        "protein_g": 20.0,
        "carb_g": 30.0,
        "fat_g": 10.0,
        "cook_minutes": 20,
        "steps": "炒熟调味",
    }


def _week_payload(recipes: List[Dict[str, Any]]) -> Dict[str, Any]:
    days = []
    for offset, recipe in enumerate(recipes):
        day = WEEK_START + timedelta(days=offset)
        days.append(
            {
                "date": str(day),
                "day_type": "weekend" if day.weekday() >= 5 else "weekday",
                "meals": {"dinner": {"recipes": [recipe]}},
            }
        )
    return {"week_menu": days}


async def _seed_library(db, count: int, prefix: str = "本地菜") -> None:
    for index in range(count):
        ingredient = await make_ingredient(db, f"{prefix}食材{index}")
        await make_recipe(db, f"{prefix}{index}", ingredient, 100, calories=500)
    await db.flush()


async def _reload_menu(db, menu_id: int) -> Menu:
    """重新取菜单并预加载 items/recipe, 避免异步上下文外触发懒加载"""
    stmt = (
        select(Menu)
        .options(selectinload(Menu.menu_items).selectinload(MenuItem.recipe))
        .where(Menu.id == menu_id)
    )
    return (await db.execute(stmt)).scalar_one()


async def test_local_first_fills_week_and_skips_llm(db_session):
    user = await make_user(db_session, open_id="ou_local_full")
    await make_preferences(db_session, user.id)
    await _seed_library(db_session, TOTAL_SLOTS)
    await db_session.commit()

    llm = SpyLLM(explode=True)
    outcome = await MenuGenerationPipeline(llm).run(user.id, WEEK_START)

    assert llm.calls == 0  # 本地拼齐 -> 完全不碰模型

    await db_session.rollback()
    menu = await db_session.get(Menu, outcome.menu_id)
    assert menu is not None
    assert menu.source == "local"
    items = (
        await db_session.execute(select(MenuItem).where(MenuItem.menu_id == outcome.menu_id))
    ).scalars().all()
    assert len(items) == TOTAL_SLOTS
    assert len({item.recipe_id for item in items}) == TOTAL_SLOTS  # 一周内不重复


async def test_insufficient_local_library_falls_back_with_hints(db_session):
    user = await make_user(db_session, open_id="ou_local_thin")
    await make_preferences(db_session, user.id)
    await _seed_library(db_session, 2, prefix="稀少菜")
    await db_session.commit()

    llm = SpyLLM(_week_payload([_dish("AI 兜底菜")]))
    outcome = await MenuGenerationPipeline(llm).run(user.id, WEEK_START)

    assert llm.calls >= 1  # 本地不足 -> 交给模型

    await db_session.rollback()
    menu = await db_session.get(Menu, outcome.menu_id)
    assert menu.source == "mixed"  # 带本地候选短名单


async def test_mode_ai_skips_local_composer(monkeypatch, db_session):
    user = await make_user(db_session, open_id="ou_mode_ai")
    await make_preferences(db_session, user.id)
    await _seed_library(db_session, TOTAL_SLOTS)  # 即使本地够满
    await db_session.commit()

    calls = {"n": 0}

    async def spy(self, ctx):
        calls["n"] += 1
        raise AssertionError("mode=ai 不应触发本地编排")

    monkeypatch.setattr(MenuGenerationPipeline, "compose_from_local", spy)

    llm = SpyLLM(_week_payload([_dish("纯 AI 菜")]))
    outcome = await MenuGenerationPipeline(llm).run(user.id, WEEK_START, mode=MODE_AI)

    assert calls["n"] == 0
    assert llm.calls >= 1

    await db_session.rollback()
    menu = await db_session.get(Menu, outcome.menu_id)
    assert menu.source == "ai"  # 没有本地候选短名单


async def test_replacement_prefers_local_when_available(db_session):
    user = await make_user(db_session, open_id="ou_replace_local")
    await make_preferences(db_session, user.id)
    ingredient = await make_ingredient(db_session, "土豆")
    current = await make_recipe(db_session, "醋溜土豆", ingredient, 200, calories=300)
    await make_recipe(db_session, "清炒时蔬", ingredient, 150, calories=350)
    menu = await make_menu(db_session, user.id, {0: [(current, "dinner")]}, week_start=WEEK_START)
    await db_session.commit()

    menu = await _reload_menu(db_session, menu.id)
    service = ReplacementService(db_session)
    result = await service.replace(menu, menu.menu_items[0], user.id, MenuItemReplaceRequest())

    assert result.source == "local"
    assert result.recipe.name == "清炒时蔬"


async def test_menu_source_is_serialized(db_session):
    user = await make_user(db_session, open_id="ou_serialize_source")
    await make_preferences(db_session, user.id)
    ingredient = await make_ingredient(db_session, "西红柿")
    recipe = await make_recipe(db_session, "西红柿炒蛋", ingredient, 200)
    menu = await make_menu(db_session, user.id, {0: [(recipe, "dinner")]}, week_start=WEEK_START)
    menu.source = "local"
    await db_session.commit()

    menu = await _reload_menu(db_session, menu.id)
    detail = await MenuService(db_session).serialize(menu)

    assert detail["source"] == "local"
    assert detail["week_start_date"] == str(WEEK_START)


async def test_replacement_never_repeats_a_recently_seen_dish(db_session):
    """连续「换一道」不能在两三道菜之间来回跳

    修复前 exclude_names 只来自「当前菜单里现存的菜」, A 换成 B 之后 A 就出集合了,
    下一次打分它又是高分候选 —— 表现就是点一次换回去、再点一次又换回来。
    """
    user = await make_user(db_session, open_id="ou_replace_no_loop")
    await make_preferences(db_session, user.id)
    ingredient = await make_ingredient(db_session, "鸡蛋")
    dishes = [
        await make_recipe(db_session, f"循环候选{i}", ingredient, 100, calories=300)
        for i in range(1, 5)
    ]
    # commit 之后 ORM 对象会过期, 先把要用的菜名留成纯字符串
    first_name = dishes[0].name
    menu = await make_menu(
        db_session, user.id, {0: [(dishes[0], "dinner")]}, week_start=WEEK_START
    )
    await db_session.commit()

    # 访问关系前先 reload, 否则会以同步方式触发 IO
    menu = await _reload_menu(db_session, menu.id)
    item_id = menu.menu_items[0].id
    served = [first_name]
    for _ in range(3):
        menu = await _reload_menu(db_session, menu.id)
        item = next(row for row in menu.menu_items if row.id == item_id)
        result = await ReplacementService(db_session).replace(
            menu, item, user.id, MenuItemReplaceRequest()
        )
        assert result.source == "local", "库里还有没上过的菜, 不该掉进 AI 降级"
        assert result.recipe.name not in served, f"又把「{result.recipe.name}」端回来了"
        served.append(result.recipe.name)
        await db_session.commit()

    # 4 道菜轮流上过一遍, 没有任何一道重复登台
    assert len(set(served)) == 4
