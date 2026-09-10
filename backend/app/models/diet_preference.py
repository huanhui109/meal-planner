"""饮食偏好模型"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DietPreference(Base, TimestampMixin):
    __tablename__ = "diet_preference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    cuisines: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="偏好菜系, JSON数组格式"
    )
    spice_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2, comment="辣度 0-5")
    flavor_preference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="口味倾向")
    staple_preference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="主食偏好")

    # 关系
    user = relationship("User", back_populates="diet_preference")
