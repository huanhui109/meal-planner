"""菜单来源标识 (本地菜谱库优先 vs LLM 生成)

Revision ID: 0007_menu_source
Revises: 0006_user_feishu
Create Date: 2026-09-11

V2.3 起, 生成周菜单会优先从本地菜谱库编排: 候选填充率达标就用本地菜谱拼一周
(``source='local'``), 不足才回落 LLM (``source='ai'``); 若把本地候选作为短名单
喂给模型混合生成, 记 ``mixed``。前端据此标注「本地菜谱库 / AI 生成」。

存量菜单一律回填 ``ai`` (它们确实由模型生成)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_menu_source"
down_revision = "0006_user_feishu"
branch_labels = None
depends_on = None

TABLE = "menu"
COLUMN = "source"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.String(length=20),
            nullable=False,
            server_default="ai",
            comment="菜单来源: local/ai/mixed",
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
