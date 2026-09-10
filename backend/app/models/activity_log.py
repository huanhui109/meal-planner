"""活动流水 - 记录系统为用户做过的事

三个用途:
  1. 今日页的流程时间线 (08:00 菜单推送 / 17:30 库存监测 / 做饭扣减)
  2. 我的页的机器人状态卡 (最近推送时间与结果)
  3. 拍照识别的每日配额计数 (按 user + kind 数当天条数)

刻意不做成"通知表": 它同时要装推送结果和接口调用记录, 所以叫活动流水。
多 worker 部署下配额计数也走这张表, 不会因为进程数被放大。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, comment="所属用户"
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="system", comment="通道: feishu/vision/system"
    )
    kind: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="事件类型: daily_menu_push/evening_check/expiry_check/vision_recognize",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", comment="一句话说明")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="补充说明")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sent", comment="结果: sent/failed/skipped"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False, comment="发生时间"
    )

    __table_args__ = (Index("ix_activity_user_kind_time", "user_id", "kind", "occurred_at"),)
