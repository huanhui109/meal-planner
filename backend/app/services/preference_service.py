"""F1 用户偏好管理 - 业务逻辑"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allergy_restriction import AllergyRestriction
from app.models.budget import Budget
from app.models.diet_preference import DietPreference
from app.models.health_goal import HealthGoal
from app.models.household import Household
from app.schemas.preference import (
    AllergyResponse,
    AllergyUpdate,
    BudgetResponse,
    BudgetUpdate,
    DietPreferenceResponse,
    DietPreferenceUpdate,
    HealthGoalResponse,
    HealthGoalUpdate,
    HouseholdResponse,
    HouseholdUpdate,
    UserPreferenceSummary,
)
from app.schemas.serializers import dumps_list, json_list


class PreferenceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Household ---

    async def get_household(self, user_id: int) -> Optional[Household]:
        result = await self.db.execute(select(Household).where(Household.user_id == user_id))
        return result.scalar_one_or_none()

    async def update_household(self, user_id: int, data: HouseholdUpdate) -> Household:
        existing = await self.get_household(user_id)
        if existing:
            existing.member_count = data.member_count
            existing.meals_per_day = data.meals_per_day
            existing.kitchen_equipments = dumps_list(data.kitchen_equipments)
            existing.weekday_cook_minutes = data.weekday_cook_minutes
            existing.weekend_cook_minutes = data.weekend_cook_minutes
            return existing
        household = Household(
            user_id=user_id,
            member_count=data.member_count,
            meals_per_day=data.meals_per_day,
            kitchen_equipments=dumps_list(data.kitchen_equipments),
            weekday_cook_minutes=data.weekday_cook_minutes,
            weekend_cook_minutes=data.weekend_cook_minutes,
        )
        self.db.add(household)
        await self.db.flush()
        return household

    # --- Diet Preference ---

    async def get_diet_preference(self, user_id: int) -> Optional[DietPreference]:
        result = await self.db.execute(select(DietPreference).where(DietPreference.user_id == user_id))
        return result.scalar_one_or_none()

    async def update_diet_preference(self, user_id: int, data: DietPreferenceUpdate) -> DietPreference:
        existing = await self.get_diet_preference(user_id)
        if existing:
            existing.cuisines = dumps_list(data.cuisines)
            existing.spice_level = data.spice_level
            existing.flavor_preference = data.flavor_preference
            existing.staple_preference = data.staple_preference
            return existing
        pref = DietPreference(
            user_id=user_id,
            cuisines=dumps_list(data.cuisines),
            spice_level=data.spice_level,
            flavor_preference=data.flavor_preference,
            staple_preference=data.staple_preference,
        )
        self.db.add(pref)
        await self.db.flush()
        return pref

    # --- Allergy ---

    async def get_allergy(self, user_id: int) -> Optional[AllergyRestriction]:
        result = await self.db.execute(
            select(AllergyRestriction).where(AllergyRestriction.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_allergy(self, user_id: int, data: AllergyUpdate) -> AllergyRestriction:
        existing = await self.get_allergy(user_id)
        if existing:
            existing.allergens = dumps_list(data.allergens)
            existing.avoid_ingredients = dumps_list(data.avoid_ingredients)
            existing.dietary_restrictions = data.dietary_restrictions or ""
            return existing
        allergy = AllergyRestriction(
            user_id=user_id,
            allergens=dumps_list(data.allergens),
            avoid_ingredients=dumps_list(data.avoid_ingredients),
            dietary_restrictions=data.dietary_restrictions or "",
        )
        self.db.add(allergy)
        await self.db.flush()
        return allergy

    # --- Health Goal ---

    async def get_health_goal(self, user_id: int) -> Optional[HealthGoal]:
        result = await self.db.execute(select(HealthGoal).where(HealthGoal.user_id == user_id))
        return result.scalar_one_or_none()

    async def update_health_goal(self, user_id: int, data: HealthGoalUpdate) -> HealthGoal:
        existing = await self.get_health_goal(user_id)
        if existing:
            if data.goal_type is not None:
                existing.goal_type = data.goal_type
            if data.daily_calories is not None:
                existing.daily_calories = data.daily_calories
            if data.protein_pct is not None:
                existing.protein_pct = data.protein_pct
            if data.carb_pct is not None:
                existing.carb_pct = data.carb_pct
            if data.fat_pct is not None:
                existing.fat_pct = data.fat_pct
            return existing
        goal = HealthGoal(
            user_id=user_id,
            goal_type=data.goal_type,
            daily_calories=data.daily_calories,
            protein_pct=data.protein_pct,
            carb_pct=data.carb_pct,
            fat_pct=data.fat_pct,
        )
        self.db.add(goal)
        await self.db.flush()
        return goal

    # --- Budget ---

    async def get_budget(self, user_id: int) -> Optional[Budget]:
        result = await self.db.execute(select(Budget).where(Budget.user_id == user_id))
        return result.scalar_one_or_none()

    async def update_budget(self, user_id: int, data: BudgetUpdate) -> Budget:
        existing = await self.get_budget(user_id)
        if existing:
            existing.weekday_daily_budget = data.weekday_daily_budget
            existing.weekend_daily_budget = data.weekend_daily_budget
            existing.weekly_cap = data.weekly_cap
            existing.min_meal_budget = data.min_meal_budget
            existing.takeout_reference_price = data.takeout_reference_price
            return existing
        budget = Budget(
            user_id=user_id,
            weekday_daily_budget=data.weekday_daily_budget,
            weekend_daily_budget=data.weekend_daily_budget,
            weekly_cap=data.weekly_cap,
            min_meal_budget=data.min_meal_budget,
            takeout_reference_price=data.takeout_reference_price,
        )
        self.db.add(budget)
        await self.db.flush()
        return budget

    # --- Summary ---

    async def get_summary(self, user_id: int) -> UserPreferenceSummary:
        """一次性获取用户全部偏好"""
        household = await self.get_household(user_id)
        diet = await self.get_diet_preference(user_id)
        allergy = await self.get_allergy(user_id)
        health = await self.get_health_goal(user_id)
        budget = await self.get_budget(user_id)

        return UserPreferenceSummary(
            household=HouseholdResponse.model_validate(household) if household else None,
            diet_preference=DietPreferenceResponse.model_validate(diet) if diet else None,
            allergy_restriction=AllergyResponse.model_validate(allergy) if allergy else None,
            health_goal=HealthGoalResponse.model_validate(health) if health else None,
            budget=BudgetResponse.model_validate(budget) if budget else None,
        )

    # --- Prompt Context ---

    async def get_preference_prompt_context(self, user_id: int) -> str:
        """将用户偏好序列化为 Prompt 可用文本, 用于菜谱生成"""
        lines = []
        household = await self.get_household(user_id)
        if household:
            lines.append(f"家庭人数: {household.member_count}")
            lines.append(f"每日餐次: {household.meals_per_day}")
            lines.append(f"工作日做饭时间: {household.weekday_cook_minutes} 分钟")
            lines.append(f"周末做饭时间: {household.weekend_cook_minutes} 分钟")

        diet = await self.get_diet_preference(user_id)
        if diet:
            cuisines = json_list(diet.cuisines)
            lines.append(f"偏好菜系: {', '.join(cuisines)}")
            lines.append(f"辣度: {diet.spice_level}/5")
            if diet.flavor_preference:
                lines.append(f"口味倾向: {diet.flavor_preference}")
            if diet.staple_preference:
                lines.append(f"主食偏好: {diet.staple_preference}")

        allergy = await self.get_allergy(user_id)
        if allergy:
            allergens = json_list(allergy.allergens)
            if allergens:
                lines.append(f"过敏源 (绝对禁止): {', '.join(allergens)}")
            avoids = json_list(allergy.avoid_ingredients)
            if avoids:
                lines.append(f"忌口食材 (尽量避免): {', '.join(avoids)}")
            if allergy.dietary_restrictions:
                lines.append(f"饮食限制: {allergy.dietary_restrictions}")

        health = await self.get_health_goal(user_id)
        if health:
            lines.append(f"健康目标: {health.goal_type or '维持'}")
            if health.daily_calories:
                lines.append(f"每日目标热量: {health.daily_calories} kcal")
            if health.protein_pct:
                lines.append(
                    f"营养比例: 蛋白{health.protein_pct}%/碳水{health.carb_pct}%/脂肪{health.fat_pct}%"
                )

        return "\n".join(lines)
