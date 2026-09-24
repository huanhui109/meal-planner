"""事件上报表 (audit T2.6)

批量落库, 索引按 event_name / user_id / 时间走, 配合后端 admin 查 DAU
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_event"
down_revision = "0009_build_info"
branch_labels = None
depends_on = None

TABLE = "event"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="触发用户, 匿名事件为空",
        ),
        sa.Column(
            "event_name",
            sa.String(length=64),
            nullable=False,
            comment="事件名 e.g. 'login' / 'generate_menu'",
        ),
        sa.Column(
            "ts",
            sa.BigInteger(),
            nullable=False,
            comment="客户端 Unix 毫秒时间戳",
        ),
        sa.Column(
            "properties",
            sa.Text(),
            nullable=True,
            comment="业务字段 JSON 字符串",
        ),
        sa.Column(
            "app_version",
            sa.String(length=40),
            nullable=True,
            comment="小程序版本号",
        ),
        sa.Column(
            "platform",
            sa.String(length=40),
            nullable=True,
            comment="客户端平台 (weapp/h5/mini-app)",
        ),
        sa.Column(
            "received_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_event_user", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 按事件名 + 时间: 漏斗分析常用查询
    op.create_index("ix_event_name_ts", TABLE, ["event_name", "ts"])
    # 按用户 + 时间: 用户行为时间线
    op.create_index("ix_event_user_ts", TABLE, ["user_id", "ts"])
    # 按服务端接收时间: 数据治理 (清洗老数据 / 监控上报延迟)
    op.create_index("ix_event_received_at", TABLE, ["received_at"])


def downgrade() -> None:
    # 只删表, 不单独 drop_index: MySQL 里 DROP TABLE 会连带删掉索引与外键,
    # 而单独删一个被外键依赖的索引会报 1553
    # (Cannot drop index ... needed in a foreign key constraint)。
    # 先 drop_index 的写法在 SQLite 上能过、MySQL 上必炸 —— 这条回滚链路一直是坏的。
    op.drop_table(TABLE)
