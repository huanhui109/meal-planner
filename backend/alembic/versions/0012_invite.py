"""邀请关系表 (audit T3.1)

invite_code 唯一; 被邀请人 (invitee_id) 兑换后填写
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_invite"
down_revision = "0011_subscribe_message"
branch_labels = None
depends_on = None

TABLE = "invite"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inviter_id", sa.Integer(), nullable=False, comment="邀请人"),
        sa.Column(
            "invitee_id",
            sa.Integer(),
            nullable=True,
            comment="被邀请人, 兑换后填",
        ),
        sa.Column(
            "invite_code",
            sa.String(length=20),
            nullable=False,
            comment="邀请码 (短码)",
        ),
        sa.Column(
            "rewarded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="奖励是否已发放",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True, comment="被邀请人兑换时间"),
        sa.ForeignKeyConstraint(
            ["inviter_id"], ["user.id"], name="fk_invite_inviter", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invitee_id"], ["user.id"], name="fk_invite_invitee", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_code", name="uq_invite_code"),
    )
    op.create_index("ix_invite_code", TABLE, ["invite_code"])
    op.create_index("ix_invite_inviter", TABLE, ["inviter_id", "created_at"])


def downgrade() -> None:
    # 只删表, 不单独 drop_index: MySQL 中 DROP TABLE 会连带删掉索引与外键,
    # 而单独删一个被外键依赖的索引会报 1553
    # (Cannot drop index ... needed in a foreign key constraint)。
    # 之前先 drop_index 的写法在 SQLite 上能过、在 MySQL 上必炸,
    # 导致 downgrade base 这条回滚链路实际上一直是坏的。
    op.drop_table(TABLE)
