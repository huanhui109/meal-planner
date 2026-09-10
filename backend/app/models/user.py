"""用户模型"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """平台用户 - 飞书扫码 / 微信小程序 / 本地开发登录创建"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    open_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        comment="第三方身份命名空间: ou_* 飞书 / wechat:* 微信小程序 / dev:* 本地开发",
    )
    union_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, comment="飞书 union_id (开发者内唯一)"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="", comment="昵称")
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="头像地址")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近登录时间")

    household = relationship("Household", back_populates="user", uselist=False, cascade="all, delete-orphan")
    diet_preference = relationship(
        "DietPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    allergy_restriction = relationship(
        "AllergyRestriction", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    health_goal = relationship(
        "HealthGoal", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    budget = relationship("Budget", back_populates="user", uselist=False, cascade="all, delete-orphan")
    feishu_config = relationship(
        "UserFeishuConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
