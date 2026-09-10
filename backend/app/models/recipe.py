"""菜谱模型"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="菜名")
    cuisine: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="菜系")
    difficulty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="难度 1-5")
    cook_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="烹饪时间(分钟)")
    calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="热量(kcal)")
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="蛋白质(g)")
    carb_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="碳水(g)")
    fat_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="脂肪(g)")
    steps: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="烹饪步骤")
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default="ai_generated",
        comment="来源: ai_generated/user_created/template",
    )

    recipe_ingredients = relationship(
        "RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )


class RecipeIngredient(Base, TimestampMixin):
    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredient.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="用量(标准单位), 无法量化时为 NULL"
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", comment="标准单位")
    amount_text: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="LLM 返回的原始用量文本, 如 '适量'"
    )

    recipe = relationship("Recipe", back_populates="recipe_ingredients")
    ingredient = relationship("Ingredient", lazy="selectin")
