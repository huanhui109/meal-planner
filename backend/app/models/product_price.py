"""商品价格历史 (audit T4.1 V3.0)

每个商品的历史价格点, 用作 V3.0 后期「价格趋势 / 比价推荐」依据
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductPrice(Base):
    __tablename__ = "product_price"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    # 抓取来源 (scheduler / manual / specific platform spider)
    source: Mapped[Optional[str]] = mapped_column(default="scheduler", nullable=True)
