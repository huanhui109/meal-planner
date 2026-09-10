"""预算配置模型"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Budget(Base, TimestampMixin):
    __tablename__ = "budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    weekday_daily_budget: Mapped[float] = mapped_column(Float, nullable=False, default=35.0, comment="工作日每日预算(元)")
    weekend_daily_budget: Mapped[float] = mapped_column(Float, nullable=False, default=80.0, comment="周末每日预算(元)")
    weekly_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="周预算上限(元)")
    min_meal_budget: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=8.0, comment="单餐预算下限(元)")

    # 关系
    user = relationship("User", back_populates="budget")
