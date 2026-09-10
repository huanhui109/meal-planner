"""F2.2 营养均衡校验 - 基于快照对象计算, 不触碰 ORM 懒加载"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

CALORIE_TOLERANCE_PCT = 20.0
MACRO_TOLERANCE_POINTS = 10.0

KCAL_PER_GRAM_PROTEIN = 4.0
KCAL_PER_GRAM_CARB = 4.0
KCAL_PER_GRAM_FAT = 9.0


@dataclass
class MealSnapshot:
    """一餐的营养快照"""
    meal_date: date
    meal_type: str
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carb_g: Optional[float] = None
    fat_g: Optional[float] = None


@dataclass
class DayNutrition:
    """单日营养汇总"""
    date: str
    calories: float
    protein_g: float
    carb_g: float
    fat_g: float
    protein_pct: float
    carb_pct: float
    fat_pct: float
    meal_count: int


@dataclass
class NutritionReport:
    passed: bool
    days_count: int
    daily_details: List[DayNutrition] = field(default_factory=list)
    weekly_avg_calories: float = 0.0
    target_calories: Optional[float] = None
    issues: List[str] = field(default_factory=list)


class NutritionService:
    """校验每日热量与三大营养素供能比"""

    def validate(
        self,
        meals: List[MealSnapshot],
        target_calories: Optional[float] = None,
        protein_pct: Optional[float] = None,
        carb_pct: Optional[float] = None,
        fat_pct: Optional[float] = None,
    ) -> NutritionReport:
        issues: List[str] = []
        if not meals:
            return NutritionReport(
                passed=False,
                days_count=0,
                issues=["菜单没有任何菜品, 无法校验营养"],
                target_calories=target_calories,
            )

        grouped: Dict[date, List[MealSnapshot]] = {}
        for meal in meals:
            grouped.setdefault(meal.meal_date, []).append(meal)

        daily_details: List[DayNutrition] = []
        for day in sorted(grouped.keys()):
            day_meals = grouped[day]
            calories = sum(m.calories or 0 for m in day_meals)
            protein = sum(m.protein_g or 0 for m in day_meals)
            carb = sum(m.carb_g or 0 for m in day_meals)
            fat = sum(m.fat_g or 0 for m in day_meals)
            macro_kcal = (
                protein * KCAL_PER_GRAM_PROTEIN
                + carb * KCAL_PER_GRAM_CARB
                + fat * KCAL_PER_GRAM_FAT
            )
            detail = DayNutrition(
                date=str(day),
                calories=round(calories, 1),
                protein_g=round(protein, 1),
                carb_g=round(carb, 1),
                fat_g=round(fat, 1),
                protein_pct=round(protein * KCAL_PER_GRAM_PROTEIN / macro_kcal * 100, 1) if macro_kcal else 0.0,
                carb_pct=round(carb * KCAL_PER_GRAM_CARB / macro_kcal * 100, 1) if macro_kcal else 0.0,
                fat_pct=round(fat * KCAL_PER_GRAM_FAT / macro_kcal * 100, 1) if macro_kcal else 0.0,
                meal_count=len(day_meals),
            )
            daily_details.append(detail)

            if target_calories:
                deviation = abs(detail.calories - target_calories) / target_calories * 100
                if deviation > CALORIE_TOLERANCE_PCT:
                    issues.append(
                        f"{detail.date} 热量 {detail.calories:.0f}kcal 偏离目标 {target_calories:.0f}kcal 超过 {CALORIE_TOLERANCE_PCT:.0f}%"
                    )
            for label, actual, target in (
                ("蛋白质", detail.protein_pct, protein_pct),
                ("碳水", detail.carb_pct, carb_pct),
                ("脂肪", detail.fat_pct, fat_pct),
            ):
                if target and abs(actual - target) > MACRO_TOLERANCE_POINTS:
                    issues.append(f"{detail.date} {label}供能比 {actual:.0f}% 偏离目标 {target:.0f}%")

        days_count = len(daily_details)
        weekly_avg = sum(d.calories for d in daily_details) / days_count if days_count else 0.0
        return NutritionReport(
            passed=not issues,
            days_count=days_count,
            daily_details=daily_details,
            weekly_avg_calories=round(weekly_avg, 1),
            target_calories=target_calories,
            issues=issues,
        )
