"""本地演示 LLM 单元测试 - 保证假数据能通过真实 schema 校验"""
from __future__ import annotations

from app.llm.demo_client import DemoLLMClient, build_demo_week_menu
from app.schemas.recipe import WeekMenuGenerate


def test_demo_payload_matches_generate_schema():
    week = WeekMenuGenerate(**build_demo_week_menu())
    assert len(week.week_menu) == 7
    for day in week.week_menu:
        assert set(day.meals.keys()) == {"lunch", "dinner"}
        for meal in day.meals.values():
            assert len(meal.recipes) == 1
            recipe = meal.recipes[0]
            assert recipe.name
            assert recipe.ingredients
            assert recipe.calories > 0
            assert recipe.steps


def test_demo_dates_are_left_blank_for_backend_alignment():
    """日期留空, 由 pipeline 的 _day_dates 按周一对齐"""
    week = WeekMenuGenerate(**build_demo_week_menu())
    assert all(day.date == "" for day in week.week_menu)


def test_demo_llm_chat_returns_json():
    import asyncio
    import json

    raw = asyncio.run(DemoLLMClient().chat([{"role": "user", "content": "hi"}]))
    parsed = json.loads(raw)
    assert len(parsed["week_menu"]) == 7


def test_demo_dishes_avoid_common_allergen():
    """演示菜单不应包含花生等常见过敏源, 免得第一次跑就被剔除"""
    week = WeekMenuGenerate(**build_demo_week_menu())
    haystack = " ".join(
        [recipe.name for day in week.week_menu for meal in day.meals.values() for recipe in meal.recipes]
        + [
            item.name
            for day in week.week_menu
            for meal in day.meals.values()
            for recipe in meal.recipes
            for item in recipe.ingredients
        ]
    )
    assert "花生" not in haystack
