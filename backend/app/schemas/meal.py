from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MealSlotName = Literal["breakfast", "lunch", "dinner", "late_night"]
MealMode = Literal["auto", "cook", "takeout"]
# 与 shared/dish-category.ts / dish_rules.DishCategory.ALL 一致, parity 测试会钉住
DishCategoryCode = Literal["chinese", "western", "japanese_korean", "southeast_asian", "other"]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class MealContext(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    meal_date: date
    meal_slot: MealSlotName
    mode: MealMode = "auto"
    servings: int = Field(default=1, ge=1, le=20)
    max_minutes: int = Field(default=30, ge=5, le=180)
    budget: Optional[float] = Field(default=None, gt=0, le=5000)
    max_spice: int = Field(default=2, ge=0, le=4)
    avoid: list[ShortText] = Field(default_factory=list, max_length=30)
    vegetarian: bool = False
    light: bool = False
    use_fridge: bool = True
    avoid_recent: bool = True
    # 长期口味里的互斥大类; None = 不限(不过滤候选), 但方案内类别一致仍是硬规则
    dish_category: Optional[DishCategoryCode] = None


class MealContextPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    meal_date: Optional[date] = None
    meal_slot: Optional[MealSlotName] = None
    mode: Optional[MealMode] = None
    servings: Optional[int] = Field(default=None, ge=1, le=20)
    max_minutes: Optional[int] = Field(default=None, ge=5, le=180)
    budget: Optional[float] = Field(default=None, gt=0, le=5000)
    max_spice: Optional[int] = Field(default=None, ge=0, le=4)
    avoid: Optional[list[ShortText]] = Field(default=None, max_length=30)
    vegetarian: Optional[bool] = None
    light: Optional[bool] = None
    use_fridge: Optional[bool] = None
    avoid_recent: Optional[bool] = None
    dish_category: Optional[DishCategoryCode] = None


class MealProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: MealContextPatch = Field(default_factory=MealContextPatch)
    expected_revision: int = Field(ge=0)


class MealActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    deduct_inventory: bool = False


class AssistantSaveRequest(MealProposeRequest):
    candidate_keys: list[ShortText] = Field(min_length=1, max_length=6)
    reason: str = Field(default="", max_length=200)


class AssistantGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="饭决 Skill", min_length=1, max_length=80)
