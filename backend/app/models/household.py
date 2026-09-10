"""家庭信息模型"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Household(Base, TimestampMixin):
    __tablename__ = "household"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="家庭人数")
    meals_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=2, comment="每日餐次")
    kitchen_equipments: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="厨房设备, JSON数组格式")
    weekday_cook_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30, comment="工作日做饭时间(分钟)")
    weekend_cook_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, comment="周末做饭时间(分钟)")

    # 关系
    user = relationship("User", back_populates="household")
