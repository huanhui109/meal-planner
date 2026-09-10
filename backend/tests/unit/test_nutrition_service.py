"""营养校验单元测试"""
from __future__ import annotations

from datetime import date

from app.services.nutrition_service import MealSnapshot, NutritionService

DAY_ONE = date(2026, 3, 2)
DAY_TWO = date(2026, 3, 3)


def snapshot(day: date, calories: int, protein=30.0, carb=40.0, fat=12.0) -> MealSnapshot:
    return MealSnapshot(
        meal_date=day,
        meal_type="lunch",
        calories=calories,
        protein_g=protein,
        carb_g=carb,
        fat_g=fat,
    )


def test_empty_menu_is_reported_as_failure():
    report = NutritionService().validate([])
    assert report.passed is False
    assert report.days_count == 0
    assert "菜单没有任何菜品" in report.issues[0]


def test_daily_totals_are_grouped_by_date():
    report = NutritionService().validate(
        [snapshot(DAY_ONE, 400), snapshot(DAY_ONE, 600), snapshot(DAY_TWO, 700)]
    )
    assert report.days_count == 2
    assert report.daily_details[0].calories == 1000
    assert report.daily_details[0].meal_count == 2
    assert report.daily_details[1].calories == 700
    assert report.weekly_avg_calories == 850.0


def test_macro_percentages_use_energy_weights():
    report = NutritionService().validate([snapshot(DAY_ONE, 800, protein=40, carb=40, fat=20)])
    day = report.daily_details[0]
    # 蛋白 160kcal + 碳水 160kcal + 脂肪 180kcal = 500kcal
    assert day.protein_pct == 32.0
    assert day.carb_pct == 32.0
    assert day.fat_pct == 36.0


def test_calorie_deviation_beyond_tolerance_is_flagged():
    report = NutritionService().validate([snapshot(DAY_ONE, 500)], target_calories=1000)
    assert report.passed is False
    assert any("偏离目标" in issue for issue in report.issues)


def test_calorie_within_tolerance_passes():
    report = NutritionService().validate([snapshot(DAY_ONE, 900)], target_calories=1000)
    assert report.passed is True
    assert report.issues == []


def test_macro_deviation_is_flagged():
    report = NutritionService().validate(
        [snapshot(DAY_ONE, 800, protein=80, carb=10, fat=5)],
        protein_pct=30,
        carb_pct=40,
        fat_pct=30,
    )
    assert report.passed is False
    assert any("供能比" in issue for issue in report.issues)


def test_zero_macro_does_not_divide_by_zero():
    report = NutritionService().validate(
        [snapshot(DAY_ONE, 0, protein=0, carb=0, fat=0)]
    )
    assert report.daily_details[0].protein_pct == 0.0
