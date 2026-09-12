"""用户行为事件 (audit T2.6)

上报后端做 DAU / 转化 / 行为路径分析。
批量上报 (单条 5KB, 批量上限 50 条), 失败不抛异常给前端。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Event(Base):
    """单条事件 - properties 直接存 JSON 字符串, 不强 schema"""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 允许 NULL: 匿名事件 / 启动期事件也能上报
    user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="触发事件的用户, 匿名事件为空"
    )
    event_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="事件名, e.g. 'login' / 'generate_menu'"
    )
    # 上报时间: 客户端时间, 后端存入时也记录 received_at 作为兜底
    ts: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="客户端 Unix 毫秒时间戳"
    )
    # 业务字段 - 自由 KV
    properties: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="业务字段 JSON 字符串"
    )
    # 客户端元信息 - 型号 / 微信版本 / 客户端版本
    app_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="小程序版本号"
    )
    platform: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="客户端平台 (weapp/h5/mini-app)"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        Index("ix_event_name_ts", "event_name", "ts"),
        Index("ix_event_user_ts", "user_id", "ts"),
        Index("ix_event_received_at", "received_at"),
    )

    def to_properties_dict(self) -> dict[str, Any] | None:
        if not self.properties:
            return None
        try:
            return json.loads(self.properties)
        except (ValueError, TypeError):
            return None
