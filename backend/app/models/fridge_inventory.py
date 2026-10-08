"""冰箱库存模型"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FridgeInventory(Base):
    __tablename__ = "fridge_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredient.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False, comment="数量")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="单位")
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="采购日期")
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="保质期")
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default="manual", comment="来源: manual/xiaoxiang_auto"
    )
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    updated_at = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.now, nullable=False
    )

    # 关系
    # passive_deletes=True: 批次行扣空后会被删除, 由数据库外键 (SET NULL) 处理
    # consumption_record 的外键, 不能在这里做 ORM 级联删除, 否则消耗流水会被一起抹掉。
    consumption_records = relationship(
        "ConsumptionRecord", back_populates="fridge_inventory", passive_deletes=True
    )


class ConsumptionRecord(Base):
    __tablename__ = "consumption_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 可空 + SET NULL: 批次行扣空后会被删除, 但消耗流水属于历史账, 必须保留
    fridge_inventory_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("fridge_inventory.id", ondelete="SET NULL"), nullable=True
    )
    menu_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("menu_item.id", ondelete="SET NULL"), nullable=True
    )
    # 今日饭决「做完了」也会走扣库存, 但没有 menu_item 可挂 —— 用 decision_id 把流水
    # 锚定到那次决策, 否则今日消耗的流水 menu_item_id/decision_id 全空, 既不可审计也
    # 没法写撤销逻辑。二者至多其一非空。
    decision_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("decision_log.id", ondelete="SET NULL"), nullable=True, comment="关联的今日饭决决策"
    )
    # 流水必须自解释: 只记"扣了 200"没法回答"扣的是什么"。撤销「标记已做」时,
    # 如果批次行已经因为扣空被删除, 就靠这两个字段把库存行按原样补回来。
    ingredient_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ingredient.id", ondelete="SET NULL"), nullable=True, comment="食材"
    )
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="消耗时的单位")
    quantity: Mapped[float] = mapped_column(Float, nullable=False, comment="消耗数量")
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    # 关系
    fridge_inventory = relationship("FridgeInventory", back_populates="consumption_records")
