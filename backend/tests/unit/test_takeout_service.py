"""单元测试: 自做 vs 外卖的结论规则"""
from __future__ import annotations

from app.services.takeout_service import (
    RECOMMENDED_EITHER,
    RECOMMENDED_HOMEMADE,
    RECOMMENDED_TAKEOUT,
    TakeoutService,
)


def test_recommends_homemade_and_shows_saving():
    result = TakeoutService().compare(
        homemade_cost=18.5, homemade_minutes=35, takeout_price=26.0
    )
    assert result["recommended"] == RECOMMENDED_HOMEMADE
    assert result["saving"] == 7.5
    assert "省 ¥7.5" in result["note"]
    assert result["homemade"]["cost"] == 18.5
    assert result["takeout"]["cost"] == 26.0


def test_recommends_takeout_when_it_is_cheaper():
    result = TakeoutService().compare(
        homemade_cost=30.0, homemade_minutes=20, takeout_price=22.0
    )
    assert result["recommended"] == RECOMMENDED_TAKEOUT
    assert "外卖比自做还便宜" in result["note"]


def test_marks_either_when_cooking_is_slow_and_delivery_is_fast():
    result = TakeoutService().compare(
        homemade_cost=18.0, homemade_minutes=50, takeout_price=26.0
    )
    assert result["recommended"] == RECOMMENDED_EITHER


def test_takeout_over_budget_is_spelled_out():
    result = TakeoutService().compare(
        homemade_cost=18.5,
        homemade_minutes=35,
        takeout_price=26.0,
        daily_budget=35.0,
        spent_today=0.0,
    )
    assert result["budget_remaining"] == 35.0
    assert result["budget_remaining_after_takeout"] == 9.0
    assert "还能剩 ¥9" in result["note"]


def test_takeout_exceeding_budget_is_flagged():
    result = TakeoutService().compare(
        homemade_cost=18.5,
        homemade_minutes=35,
        takeout_price=26.0,
        daily_budget=35.0,
        spent_today=20.0,
    )
    assert result["budget_remaining_after_takeout"] == -11.0
    assert "超当日预算" in result["note"]


def test_missing_values_do_not_crash_and_keep_recommendation_honest():
    result = TakeoutService().compare(
        homemade_cost=None, homemade_minutes=None, takeout_price=None
    )
    assert result["recommended"] == RECOMMENDED_HOMEMADE
    assert result["homemade"]["cost"] is None
    assert result["saving"] is None
    assert result["budget_remaining_after_takeout"] is None


def test_delivery_link_targets_meituan_platform():
    result = TakeoutService().compare(
        homemade_cost=18.0, homemade_minutes=30, takeout_price=26.0, dish_name="鸡胸肉"
    )
    assert result["platform"] == "meituan_waimai"
    assert "{keyword}" not in result["link"]
    assert result["link"].startswith("https://")
