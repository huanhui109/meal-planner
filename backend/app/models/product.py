"""商品模型 (小象超市/美团外卖) - 二期采集接入"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_platform: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="来源平台: xiaoxiang/meituan_waimai"
    )
    sku_id: Mapped[str] = mapped_column(String(200), nullable=False, comment="商品SKU ID")
    name: Mapped[str] = mapped_column(String(500), nullable=False, comment="商品名称")
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="商品分类")
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="价格(元)")
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="单位")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否在售")
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否有货")
    price_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="价格是否异常波动"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    mappings = relationship("ProductMapping", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_platform", "sku_id", name="uq_product_platform_sku"),
    )


class ProductMapping(Base):
    __tablename__ = "product_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredient.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="匹配度 0-1")
    user_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="用户是否确认"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    product = relationship("Product", back_populates="mappings")
    ingredient = relationship("Ingredient")

    __table_args__ = (
        UniqueConstraint("ingredient_id", "product_id", name="uq_mapping_ingredient_product"),
    )
