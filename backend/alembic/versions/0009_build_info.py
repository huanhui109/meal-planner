"""小程序版本元信息表 (audit T2.4)

存多个版本历史, 默认 GET 取最新一条作为 latest_version / min_version 的来源
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_build_info"
down_revision = "0008_feedback"
branch_labels = None
depends_on = None

TABLE = "build_info"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False, comment="小程序版本号"),
        sa.Column(
            "min_version",
            sa.String(length=20),
            nullable=False,
            comment="低于此版本强制升级",
        ),
        sa.Column(
            "force_update",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否强制升级",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="升级说明"),
        sa.Column(
            "update_url",
            sa.String(length=500),
            nullable=True,
            comment="跳转链接 (H5 / 商店 / 二维码页)",
        ),
        sa.Column(
            "released_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 默认按发布时倒序取最新
    op.create_index("ix_build_info_released_at", TABLE, ["released_at"])


def downgrade() -> None:
    op.drop_index("ix_build_info_released_at", table_name=TABLE)
    op.drop_table(TABLE)
