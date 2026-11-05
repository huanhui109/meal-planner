"""A meal is the shared unit of work for the web app and assistant."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MealSession(Base, TimestampMixin):
    __tablename__ = "meal_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    meal_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_slot: Mapped[str] = mapped_column(String(20), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False)
    current_proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "meal_date", "meal_slot", name="uq_meal_session_slot"),
    )


class MealProposal(Base, TimestampMixin):
    __tablename__ = "meal_proposal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("meal_session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    eaten_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_meal_proposal_user_created", "user_id", "created_at"),)


class MealEvent(Base):
    __tablename__ = "meal_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("meal_proposal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MealStockMovement(Base):
    """Self-contained receipt: deleting a depleted batch must not erase its metadata."""

    __tablename__ = "meal_stock_movement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("meal_proposal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fridge_inventory.id", ondelete="SET NULL"), nullable=True
    )
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    batch: Mapped[dict] = mapped_column(JSON, nullable=False)


class AssistantGrant(Base, TimestampMixin):
    __tablename__ = "assistant_grant"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
