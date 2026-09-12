"""邀请关系 (audit T3.1)

邀请码生成 + 兑换; 奖励发放 (AI 生成额度) 在 invite_service 里做
"""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"  # 去掉易混淆 0/o/1/l/i


def generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


class Invite(Base):
    __tablename__ = "invite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, comment="邀请人"
    )
    invitee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="被邀请人, 兑换后填"
    )
    invite_code: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, comment="邀请码 (短码)"
    )
    rewarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="奖励是否已发放"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="被邀请人兑换时间"
    )

    __table_args__ = (
        Index("ix_invite_code", "invite_code"),
        Index("ix_invite_inviter", "inviter_id", "created_at"),
    )
