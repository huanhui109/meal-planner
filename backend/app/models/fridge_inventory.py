"""冰箱库存模型"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Integer, String, Float, Date, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FridgeInventory(Base):
    __tablename__ = "fridge_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, ForeignKey("ingredient.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, comment="数量")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="单位")
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="采购日期")
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="保质期")
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="manual", comment="来源: manual/xiaoxiang_auto")
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.now, nullable=False
    )

    # 关系
    consumption_records = relationship("ConsumptionRecord", back_populates="fridge_inventory", cascade="all, delete-orphan")


class ConsumptionRecord(Base):
    __tablename__ = "consumption_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fridge_inventory_id: Mapped[int] = mapped_column(Integer, ForeignKey("fridge_inventory.id", ondelete="CASCADE"), nullable=False)
    menu_item_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("menu_item.id", ondelete="SET NULL"), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, comment="消耗数量")
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    # 关系
    fridge_inventory = relationship("FridgeInventory", back_populates="consumption_records")
