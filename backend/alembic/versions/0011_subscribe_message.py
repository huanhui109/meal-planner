"""订阅消息授权表 (audit T2.2)

记录用户授权 / 撤授权 + 推送时间
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_subscribe_message"
down_revision = "0010_event"
branch_labels = None
depends_on = None

TABLE = "subscribe_message"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "template_id",
            sa.String(length=100),
            nullable=False,
            comment="微信后台的订阅消息模板 ID",
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="最近一次用户授权时间",
        ),
        sa.Column(
            "last_declined_at",
            sa.DateTime(),
            nullable=True,
            comment="最近一次用户拒绝时间",
        ),
        sa.Column(
            "last_send_at",
            sa.DateTime(),
            nullable=True,
            comment="最近一次实际推送时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_subscribe_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # 同一用户对同一模板只有一条
        sa.UniqueConstraint("user_id", "template_id", name="uq_subscribe_user_template"),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
