"""食材模型"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="食材名称")
    category: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="分类: 蔬菜/水果/肉禽蛋/水产/调味品/乳制品"
    )
    standard_unit: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="标准单位: 个/根/颗/块/把/条/头/g/ml"
    )
    reference_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="参考单价(元/标准单位), 用于菜单成本估算"
    )
