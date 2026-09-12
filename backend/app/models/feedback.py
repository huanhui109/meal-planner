"""用户反馈 - 微信小程序/H5 收集问题、建议、菜谱纠错、其他

不做实时通知 (V1.0): 后台 /api/admin/feedback 拉取即可
匿名提交 (user_id 可空): 让用户首次启动就能反馈, 无需登录
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 允许 NULL: 匿名提交 (用户未登录也能反馈)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="所属用户, 匿名反馈为空"
    )
    # 类目: bug / suggestion / recipe / other
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other", comment="反馈类型: bug/suggestion/recipe/other"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="反馈内容")
    # 联系方式 (可选): 用户希望被回复时填, 不强制
    contact: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="联系方式 (邮箱/微信), 可选"
    )
    # 设备信息 JSON 字符串: 型号 / 系统版本 / 微信版本 / 客户端版本
    device_info: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="设备信息 JSON: 型号/系统/微信版本/客户端版本"
    )
    # 状态: open (未处理) / processing (跟进中) / closed (已关闭)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", comment="状态: open/processing/closed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False, comment="提交时间"
    )

    __table_args__ = (
        Index("ix_feedback_status_created", "status", "created_at"),
        Index("ix_feedback_user_created", "user_id", "created_at"),
    )
