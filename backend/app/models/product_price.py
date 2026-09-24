"""商品价格历史 (audit T4.1 V3.0)

每个商品的历史价格点, 用作 V3.0 后期「价格趋势 / 比价推荐」依据
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, text
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
    # 长度必须显式写: 不写时 SQLAlchemy 推出的是"无长度 VARCHAR",
    # MySQL 直接拒绝 (VARCHAR requires a length), 而 SQLite 不检查 ——
    # 这是 create_all 只在 SQLite 上跑过才会漏掉的一类不一致。
    # 迁移 0013 里这一列就是 String(50), 模型必须跟它对齐。
    source: Mapped[Optional[str]] = mapped_column(String(50), default="scheduler", nullable=True)
