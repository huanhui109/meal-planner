"""菜单与菜单生成任务模型"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MenuStatus:
    """菜单状态机取值"""

    DRAFT = "draft"  # 生成完成, 可编辑
    CONFIRMED = "confirmed"  # 用户确认本周菜单
    ACTIVE = "active"  # 已进入执行期
    COMPLETED = "completed"  # 本周结束

    EDITABLE = (DRAFT, CONFIRMED)
    ALL = (DRAFT, CONFIRMED, ACTIVE, COMPLETED)


class GenerationStatus:
    """生成任务状态取值"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    ACTIVE = (PENDING, RUNNING)


class Menu(Base, TimestampMixin):
    __tablename__ = "menu"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, comment="所属用户"
    )
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="周起始日期(周一)")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MenuStatus.DRAFT,
        comment="状态: draft/confirmed/active/completed",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ai",
        server_default="ai",
        comment="来源: local 本地菜谱库 / ai 模型生成 / mixed 混合",
    )

    menu_items = relationship(
        "MenuItem", back_populates="menu", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_menu_user_week", "user_id", "week_start_date"),
        Index("ix_menu_user_status", "user_id", "status"),
    )


class MenuItem(Base):
    __tablename__ = "menu_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    menu_id: Mapped[int] = mapped_column(Integer, ForeignKey("menu.id", ondelete="CASCADE"), nullable=False)
    recipe_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="SET NULL"), nullable=True
    )
    meal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="用餐日期")
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="餐次: lunch/dinner")
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="锁定后不参与重生成"
    )
    is_cooked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否已做")
    cook_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="self", comment="self/takeout")
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="预估成本(元)")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    menu = relationship("Menu", back_populates="menu_items")
    recipe = relationship("Recipe", lazy="selectin")

    __table_args__ = (Index("ix_menu_item_menu_date", "menu_id", "meal_date"),)


class MenuGenerationTask(Base, TimestampMixin):
    """菜单生成任务 - 由后台 worker 领取执行"""

    __tablename__ = "menu_generation_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, comment="所属用户"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=GenerationStatus.PENDING,
        comment="状态: pending/running/succeeded/failed",
    )
    menu_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("menu.id", ondelete="SET NULL"), nullable=True, comment="生成成功的菜单"
    )
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="目标周起始日期")
    request_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="请求参数 JSON")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已尝试次数")
    is_regeneration: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否为重新生成 (走独立配额, 不占用首次生成额度)",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_menu_task_status_created", "status", "created_at"),
        Index("ix_menu_task_user_created", "user_id", "created_at"),
        Index("ix_menu_task_user_regen", "user_id", "is_regeneration", "created_at"),
    )
