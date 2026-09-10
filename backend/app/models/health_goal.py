"""健康目标模型"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class HealthGoal(Base, TimestampMixin):
    __tablename__ = "health_goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    goal_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="目标类型: 减脂/增肌/控糖/控压/维持")
    daily_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="每日目标热量(kcal)")
    protein_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="蛋白质百分比")
    carb_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="碳水百分比")
    fat_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="脂肪百分比")

    # 关系
    user = relationship("User", back_populates="health_goal")
