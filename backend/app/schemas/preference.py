"""用户偏好 Pydantic 数据模型"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.serializers import json_list

# === Household ===


class HouseholdUpdate(BaseModel):
    member_count: int = Field(default=1, ge=1, le=20, description="家庭人数")
    meals_per_day: int = Field(default=2, ge=1, le=5, description="每日餐次")
    kitchen_equipments: List[str] = Field(default_factory=list, description="厨房设备列表")
    weekday_cook_minutes: int = Field(default=30, ge=5, le=180, description="工作日做饭时间(分钟)")
    weekend_cook_minutes: int = Field(default=60, ge=5, le=300, description="周末做饭时间(分钟)")


class HouseholdResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_count: int
    meals_per_day: int
    kitchen_equipments: List[str] = Field(default_factory=list)
    weekday_cook_minutes: int
    weekend_cook_minutes: int

    @field_validator("kitchen_equipments", mode="before")
    @classmethod
    def _parse_equipments(cls, value):
        return json_list(value)


# === Diet Preference ===


class DietPreferenceUpdate(BaseModel):
    cuisines: List[str] = Field(default_factory=list, min_length=1, max_length=5, description="偏好菜系")
    spice_level: int = Field(default=2, ge=0, le=5, description="辣度 0-5")
    flavor_preference: Optional[str] = Field(default=None, description="口味倾向")
    staple_preference: Optional[str] = Field(default=None, description="主食偏好")


class DietPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cuisines: List[str] = Field(default_factory=list)
    spice_level: int
    flavor_preference: Optional[str] = None
    staple_preference: Optional[str] = None

    @field_validator("cuisines", mode="before")
    @classmethod
    def _parse_cuisines(cls, value):
        return json_list(value)


# === Allergy Restriction ===


class AllergyUpdate(BaseModel):
    allergens: List[str] = Field(default_factory=list, description="过敏源列表")
    avoid_ingredients: List[str] = Field(default_factory=list, description="忌口食材列表")
    dietary_restrictions: Optional[str] = Field(default="", description="饮食限制描述")


class AllergyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    allergens: List[str] = Field(default_factory=list)
    avoid_ingredients: List[str] = Field(default_factory=list)
    dietary_restrictions: Optional[str] = None

    @field_validator("allergens", "avoid_ingredients", mode="before")
    @classmethod
    def _parse_lists(cls, value):
        return json_list(value)


# === Health Goal ===


class HealthGoalUpdate(BaseModel):
    goal_type: Optional[str] = Field(default=None, description="目标类型")
    daily_calories: Optional[int] = Field(default=None, ge=800, le=5000, description="每日目标热量")
    protein_pct: Optional[int] = Field(default=None, ge=10, le=60, description="蛋白质百分比")
    carb_pct: Optional[int] = Field(default=None, ge=10, le=70, description="碳水百分比")
    fat_pct: Optional[int] = Field(default=None, ge=10, le=60, description="脂肪百分比")


class HealthGoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    goal_type: Optional[str] = None
    daily_calories: Optional[int] = None
    protein_pct: Optional[int] = None
    carb_pct: Optional[int] = None
    fat_pct: Optional[int] = None


# === Budget ===


class BudgetUpdate(BaseModel):
    weekday_daily_budget: float = Field(default=35.0, ge=5.0, le=500.0, description="工作日每日预算")
    weekend_daily_budget: float = Field(default=80.0, ge=5.0, le=1000.0, description="周末每日预算")
    weekly_cap: Optional[float] = Field(default=None, ge=0, description="周预算上限")
    min_meal_budget: Optional[float] = Field(default=8.0, ge=0, description="单餐预算下限")
    takeout_reference_price: float = Field(
        default=26.0, ge=0, le=500, description="一顿外卖的参考价(元), 今日页自做 vs 外卖用"
    )


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    weekday_daily_budget: float
    weekend_daily_budget: float
    weekly_cap: Optional[float] = None
    min_meal_budget: Optional[float] = None
    takeout_reference_price: float = 26.0


# === Summary ===


class UserPreferenceSummary(BaseModel):
    """用户全部偏好聚合"""

    household: Optional[HouseholdResponse] = None
    diet_preference: Optional[DietPreferenceResponse] = None
    allergy_restriction: Optional[AllergyResponse] = None
    health_goal: Optional[HealthGoalResponse] = None
    budget: Optional[BudgetResponse] = None
