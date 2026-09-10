"""SQLAlchemy 声明式基类与通用字段"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


class TimestampMixin:
    """时间戳混入 - 提供 created_at 和 updated_at

    server_default 使用 CURRENT_TIMESTAMP (MySQL / SQLite 均原生支持)
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.now,
        nullable=False,
    )
