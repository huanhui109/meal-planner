"""菜谱相关 Pydantic 模型"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict


class IngredientItem(BaseModel):
    name: str
    quantity: Optional[Union[float, str]] = None
    unit: str = ""


class RecipeGenerateItem(BaseModel):
    name: str
    ingredients: List[IngredientItem] = []
    calories: int = 0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    cook_minutes: int = 20
    steps: str = ""


class MealGenerateItem(BaseModel):
    recipes: List[RecipeGenerateItem] = []


class DayGenerateItem(BaseModel):
    date: str = ""
    day_type: str = "weekday"
    meals: Dict[str, MealGenerateItem] = {}


class WeekMenuGenerate(BaseModel):
    week_menu: List[DayGenerateItem] = []


class RecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    name: str
    cuisine: Optional[str] = None
    difficulty: Optional[int] = None
    cook_minutes: Optional[int] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carb_g: Optional[float] = None
    fat_g: Optional[float] = None
    steps: Optional[str] = None
    source: Optional[str] = None


class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipe_id: Optional[int] = None
    recipe: Optional[RecipeResponse] = None
    meal_date: str
    meal_type: str
    is_locked: bool = False
    is_cooked: bool = False
    cook_mode: str = "self"
    estimated_cost: Optional[float] = None


class MenuResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    week_start_date: str
    status: str
    menu_items: List[MenuItemResponse] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MenuGenerateRequest(BaseModel):
    """生成请求 - 兼容 week_start 与 week_start_date 两种字段名"""

    week_start: Optional[str] = None
    week_start_date: Optional[str] = None
    force: bool = False


class MenuItemReplaceRequest(BaseModel):
    recipe_name: str
    recipe_ingredients: List[IngredientItem] = []
    calories: int = 0
    cook_minutes: int = 20
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    steps: str = ""
