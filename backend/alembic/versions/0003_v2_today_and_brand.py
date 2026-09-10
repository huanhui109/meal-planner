"""V2.0: 外卖参考价 + 活动流水

Revision ID: 0003_v2_today
Revises: 0002_consumption_record
Create Date: 2026-09-10

两张改动都是为"今日"页服务的:
  * budget.takeout_reference_price —— 自做 vs 外卖对比用的外卖参考价。
    卡片上改价会写回这里, 所以老数据用 server_default 26.0 回填即可。
  * activity_log —— 系统为用户做过的事 (推送 / 库存监测 / 拍照识别)。
    今日页的流程时间线、我的页的机器人状态卡、拍照识别的每日配额都读它。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_v2_today"
down_revision = "0002_consumption_record"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget",
        sa.Column(
            "takeout_reference_price",
            sa.Float(),
            nullable=False,
            server_default=sa.text("26.0"),
            comment="一顿外卖的参考价(元)",
        ),
    )
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="所属用户"),
        sa.Column("channel", sa.String(length=20), nullable=False, comment="通道: feishu/vision/system"),
        sa.Column(
            "kind",
            sa.String(length=40),
            nullable=False,
            comment="事件类型: daily_menu_push/evening_check/expiry_check/vision_recognize",
        ),
        sa.Column("title", sa.String(length=200), nullable=False, comment="一句话说明"),
        sa.Column("detail", sa.Text(), nullable=True, comment="补充说明"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="结果: sent/failed/skipped"),
        sa.Column(
            "occurred_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="发生时间",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_activity_user_kind_time",
        "activity_log",
        ["user_id", "kind", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    # 不能先 DROP INDEX: MySQL 说这个索引还被 user_id 的外键用着 (errno 1553)。
    # 直接删表, 索引跟着表一起走。
    op.drop_table("activity_log")
    op.drop_column("budget", "takeout_reference_price")
