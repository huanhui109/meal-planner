"""Bidirectional wake-up bridge: token pairs, bounded tasks, audit and switch."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_inbound_bridge"
down_revision = "0025_assistant_bridge"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    # 四张新表只通过 user_id 引用 user 表, 以及新表内部 pair_id 互引。
    # 不建任何指向 AssistantGrant / WorkBuddyConnection / AssistantAdjustment 的外键,
    # 也不在既有表上加字段或索引 —— 旧桥零改动。
    op.create_table(
        "inbound_token_pair",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assistant_instance_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("web_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("assistant_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("web_secret_enc", sa.Text(), nullable=False),
        sa.Column("assistant_secret_enc", sa.Text(), nullable=False),
        sa.Column("web_state", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("assistant_state", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("allowlist_version", sa.String(20), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.Column("web_revoked_at", sa.DateTime(), nullable=True),
        sa.Column("assistant_revoked_at", sa.DateTime(), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_inbound_token_pair_user_created", "inbound_token_pair", ["user_id", "created_at"])

    op.create_table(
        "inbound_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pair_id", sa.String(36), sa.ForeignKey("inbound_token_pair.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("assistant_instance_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("allowlist_version", sa.String(20), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("message_id", sa.String(200), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("proposal_id", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(), nullable=False),
        sa.Column("poll_failures", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
    )
    op.create_index("ix_inbound_task_user_created", "inbound_task", ["user_id", "created_at"])
    op.create_index("ix_inbound_task_pair_status", "inbound_task", ["pair_id", "status"])

    op.create_table(
        "inbound_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pair_id", sa.String(36), nullable=True),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("allowlist_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_inbound_audit_event_id"),
    )
    op.create_index("ix_inbound_audit_user_created", "inbound_audit", ["user_id", "created_at"])

    op.create_table(
        "inbound_bridge_config",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def downgrade() -> None:
    # ⚠ MySQL 1553，别把 drop_index 加回来。
    # inbound_task.pair_id 的外键落在复合索引 ix_inbound_task_pair_status 的 pair_id
    # 前缀上，直接 DROP INDEX 会被外键约束挡住（1553: needed in a foreign key
    # constraint）；反过来先删父表 inbound_token_pair 又会被子表外键挡住。
    # 这里不 drop_column，索引会随 DROP TABLE 一并消失，所以按「先子表后父表」删表即可。
    # （"复合索引必须先 drop_index" 只适用于 drop_column 保留表的场景，不适用于整表删除。）
    op.drop_table("inbound_bridge_config")
    op.drop_table("inbound_audit")
    op.drop_table("inbound_task")        # child: 持有指向 inbound_token_pair 的外键
    op.drop_table("inbound_token_pair")  # parent
