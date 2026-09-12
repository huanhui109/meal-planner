"""用户订阅消息授权记录 (audit T2.2)

微信订阅消息有两种：
- 一次性订阅：用户每次手动授权后才能推送一条
- 长期订阅：仅部分类目（工具/政务）能申请，授权一次后可推多条

本表记的是用户在「我的 → 订阅」勾选的模板，方便后端做"该不该给他发"判断
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SubscribeMessage(Base):
    __tablename__ = "subscribe_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="微信后台的订阅消息模板 ID"
    )
    # 长期订阅授权时间 (一次性订阅时 == last_granted_at)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    # 用户主动撤回 / 默认每次弹都算撤回, 留个最近拒绝时间用于调度器不做无意义重发
    last_declined_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近一次用户拒绝时间"
    )
    last_send_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近一次实际推送时间"
    )

    __table_args__ = (
        Index("ix_subscribe_user_template", "user_id", "template_id", unique=True),
    )
