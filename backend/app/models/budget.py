"""预算配置模型"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Budget(Base, TimestampMixin):
    __tablename__ = "budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    weekday_daily_budget: Mapped[float] = mapped_column(
        Float, nullable=False, default=35.0, comment="工作日每日预算(元)"
    )
    weekend_daily_budget: Mapped[float] = mapped_column(
        Float, nullable=False, default=80.0, comment="周末每日预算(元)"
    )
    weekly_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="周预算上限(元)")
    min_meal_budget: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=8.0, comment="单餐预算下限(元)"
    )
    takeout_reference_price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=26.0,
        server_default=text("26.0"),
        comment="一顿外卖的参考价(元), 用于今日页的自做 vs 外卖对比; 用户在卡片上改价会写回这里",
    )

    # 关系
    user = relationship("User", back_populates="budget")
