"""模型聚合导出 - Alembic autogenerate 依赖此处的导入"""
from app.models.base import Base, TimestampMixin
from app.models.user import User
from app.models.household import Household
from app.models.diet_preference import DietPreference
from app.models.allergy_restriction import AllergyRestriction
from app.models.health_goal import HealthGoal
from app.models.budget import Budget
from app.models.ingredient import Ingredient
from app.models.recipe import Recipe, RecipeIngredient
from app.models.product import Product, ProductMapping
from app.models.fridge_inventory import FridgeInventory, ConsumptionRecord
from app.models.menu import Menu, MenuItem, MenuGenerationTask, MenuStatus, GenerationStatus
from app.models.purchase_record import PurchaseRecord

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
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
]
