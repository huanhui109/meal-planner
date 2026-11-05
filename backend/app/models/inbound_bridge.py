"""双向唤醒模块数据模型 - 四张新表。

字段严格对齐 alembic/versions/0026_inbound_bridge.py, 不改动任何既有表:
四表只通过 user_id 引用 user 表, 以及新表内部 pair_id 互引, 不与
AssistantGrant / WorkBuddyConnection / AssistantAdjustment 产生外键交叉。

安全约束:
- InboundTokenPair 只存 SHA256(明文) 哈希与 Fernet(明文) 密文, 不存令牌明文。
- InboundAudit 无 TimestampMixin (只有 created_at), 且 event_id 唯一约束兼作防重放。
- InboundBridgeConfig 固定单行 id=1, 是 L1 请求级运行开关。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class InboundTokenPair(Base, TimestampMixin):
    """一对双向令牌的绑定关系与五态。

    web_state 与 assistant_state 是两列独立状态, 单端撤销/轮换不影响另一端。
    web_token_hash / assistant_token_hash 为 UNIQUE, 用于按明文哈希查找与枚举。
    """

    __tablename__ = "inbound_token_pair"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    assistant_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    web_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    assistant_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    web_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    web_state: Mapped[str] = mapped_column(String(16), nullable=False, default="issued", server_default="issued")
    assistant_state: Mapped[str] = mapped_column(String(16), nullable=False, default="issued", server_default="issued")
    allowlist_version: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    web_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    assistant_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_inbound_token_pair_user_created", "user_id", "created_at"),)


class InboundTask(Base, TimestampMixin):
    """有界唤醒任务与状态机。

    id 即网页触发时的 request_id, 全局幂等。payload 存 candidate_keys / context 等
    服务端二次校验所需的中间数据, 不含任何令牌明文。
    """

    __tablename__ = "inbound_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    pair_id: Mapped[str] = mapped_column(ForeignKey("inbound_token_pair.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assistant_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    allowlist_version: Mapped[str] = mapped_column(String(20), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    message_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    poll_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # created_at / updated_at 由 TimestampMixin 的 CURRENT_TIMESTAMP server_default 生成。
    # AsyncSession 下 INSERT 后若 mapper 不取回默认值, WakeOrchestrator.view() 读
    # task.created_at 会触发隐式 SELECT -> MissingGreenlet。打开 eager_defaults 让
    # flush() 直接取回 server 默认值 (MySQL/SQLite 均适用), 生产链路不再依赖测试夹具兜底。
    __mapper_args__ = {"eager_defaults": True}

    __table_args__ = (
        Index("ix_inbound_task_user_created", "user_id", "created_at"),
        Index("ix_inbound_task_pair_status", "pair_id", "status"),
    )


class InboundAudit(Base):
    """审计 + 防重放。

    刻意不使用 TimestampMixin: 迁移里这张表只有 created_at 一列时间字段。
    event_id 唯一约束是全局防重放键, 也允许 consume_event_id() 插入占位行。
    字段白名单见 services/inbound_bridge/audit.py::SAFE_FIELDS, 绝不写令牌明文 /
    助手对话全文 / 用户用餐明细。
    """

    __tablename__ = "inbound_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pair_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    allowlist_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        Index("ix_inbound_audit_user_created", "user_id", "created_at"),
        UniqueConstraint("event_id", name="uq_inbound_audit_event_id"),
    )


class InboundBridgeConfig(Base):
    """L1 请求级运行开关, 固定单行 id=1。

    enabled 默认 0。置 0 立即切断入站受理并取消在途任务 (见 BridgeSwitch)。
    """

    __tablename__ = "inbound_bridge_config"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.now, nullable=False
    )
