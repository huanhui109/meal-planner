"""每个用户自己的飞书机器人配置

Revision ID: 0006_user_feishu
Revises: 0005_task_regeneration
Create Date: 2026-09-10

飞书应用凭证决定"消息以谁的身份发出去"。做成全局一份的话, 一个家庭里每个人
的飞书账号/租户不同, 共用一份配置根本发不出去 —— 所以改成每个用户配自己的。

App Secret 加密后存储 (见 app/services/secret_box.py), 前端只能拿到掩码。
没配的用户照常使用全部功能, 只是收不到飞书推送。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_user_feishu"
down_revision = "0005_task_regeneration"
branch_labels = None
depends_on = None

TABLE = "user_feishu_config"
# 与 TimestampMixin 一致: 时间戳交给数据库默认值, ORM 插入时不带这两列
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="所属用户 - 一个用户一份配置"),
        sa.Column("app_id", sa.String(length=100), nullable=False, comment="飞书应用的 App ID"),
        sa.Column(
            "app_secret_encrypted",
            sa.Text(),
            nullable=False,
            comment="App Secret, 用 secret_box 加密后存储",
        ),
        sa.Column(
            "receive_id",
            sa.String(length=200),
            nullable=False,
            comment="接收方 ID (自己的 open_id 或群 chat_id)",
        ),
        sa.Column(
            "receive_id_type",
            sa.String(length=20),
            nullable=False,
            server_default="open_id",
            comment="接收方 ID 类型: open_id / chat_id / email",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="关掉后保留配置但不再推送"
        ),
        sa.Column("remark", sa.String(length=100), nullable=False, comment="给自己看的备注"),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True, comment="最近一次测试推送成功的时间"),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近一次推送失败原因"),
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_feishu_config_user"),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
