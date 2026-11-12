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
    # 「饭决」场景标签: 如 快手/常点外卖/愿意炖一小时/在家做 (v1.0.0 迁移 0014)
    scene_tags: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="场景标签 JSON 数组"
    )
    # 家人口味: 菜品大类单选(迁移 0027)。NULL = 不限, 但「同一方案类别一致」仍是硬规则,
    # 不限只是不过滤候选, 不是允许混搭。值见 dish_category 字典表 / shared/dish-category.ts。
    dish_category: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="菜品大类(互斥单选), NULL=不限"
    )

    # 关系
    user = relationship("User", back_populates="diet_preference")
