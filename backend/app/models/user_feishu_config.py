"""用户自己的飞书机器人配置

为什么是「每用户一份」而不是全局一份:
飞书应用凭证决定"消息以谁的身份发出去"。做成全局配置的话, 部署者配一次,
所有用户共用同一个应用 —— 但飞书 tenant_access_token 只能发给该应用可见范围内的人,
一个家庭里每个人用的飞书账号/租户不同, 共用一份配置根本发不出去。

所以每个用户配自己的应用, 数据按 user_id 隔离: 谁配的谁用, 互相看不到。
没配的用户照常登录使用全部功能, 只是收不到飞书推送。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserFeishuConfig(Base, TimestampMixin):
    """用户级飞书机器人凭证"""

    __tablename__ = "user_feishu_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="所属用户 - 一个用户一份配置",
    )
    app_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", comment="飞书应用的 App ID")
    app_secret_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="App Secret, 用 secret_box 加密后存储"
    )
    receive_id: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="接收方 ID (自己的 open_id 或群 chat_id)"
    )
    receive_id_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open_id", comment="接收方 ID 类型: open_id / chat_id / email"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="关掉后保留配置但不再推送"
    )
    remark: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", comment="给自己看的备注, 例如「家庭群」"
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最近一次测试推送成功的时间"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="最近一次推送失败原因")

    user = relationship("User", back_populates="feishu_config")
