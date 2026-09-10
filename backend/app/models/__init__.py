"""模型聚合导出 - Alembic autogenerate 依赖此处的导入"""

from app.models.activity_log import ActivityLog
from app.models.allergy_restriction import AllergyRestriction
from app.models.base import Base, TimestampMixin
from app.models.budget import Budget
from app.models.diet_preference import DietPreference
from app.models.fridge_inventory import ConsumptionRecord, FridgeInventory
from app.models.health_goal import HealthGoal
from app.models.household import Household
from app.models.ingredient import Ingredient
from app.models.menu import GenerationStatus, Menu, MenuGenerationTask, MenuItem, MenuStatus
from app.models.product import Product, ProductMapping
from app.models.purchase_record import PurchaseRecord
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.models.user_feishu_config import UserFeishuConfig

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "ActivityLog",
    "Household",
    "DietPreference",
    "AllergyRestriction",
    "HealthGoal",
    "Budget",
    "Ingredient",
    "Recipe",
    "RecipeIngredient",
    "Product",
    "ProductMapping",
    "FridgeInventory",
    "ConsumptionRecord",
    "Menu",
    "MenuItem",
    "MenuGenerationTask",
    "MenuStatus",
    "GenerationStatus",
    "PurchaseRecord",
    "UserFeishuConfig",
]
