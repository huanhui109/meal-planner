"""Persistent, user-scoped host authorization and adjustment receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WorkBuddyConnection(Base, TimestampMixin):
    __tablename__ = "workbuddy_connection"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(200))
    credentials: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    state_hash: Mapped[Optional[str]] = mapped_column(String(64))
    state_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AssistantAdjustment(Base, TimestampMixin):
    __tablename__ = "assistant_adjustment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(String(200))
    error: Mapped[Optional[str]] = mapped_column(String(500))
    proposal_id: Mapped[Optional[str]] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    poll_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_assistant_adjustment_user_created", "user_id", "created_at"),)
