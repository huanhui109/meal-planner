"""过敏源与忌口模型"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AllergyRestriction(Base, TimestampMixin):
    __tablename__ = "allergy_restriction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    allergens: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="过敏源列表, JSON数组格式"
    )
    avoid_ingredients: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="忌口食材, JSON数组格式"
    )
    dietary_restrictions: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="饮食限制描述")

    # 关系
    user = relationship("User", back_populates="allergy_restriction")
