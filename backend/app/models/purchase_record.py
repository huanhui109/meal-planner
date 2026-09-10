"""采购记录模型"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Float, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PurchaseRecord(Base):
    __tablename__ = "purchase_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, comment="数量")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="金额(元)")
    platform: Mapped[str] = mapped_column(String(50), nullable=False, comment="平台: xiaoxiang/meituan_waimai/manual")
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
