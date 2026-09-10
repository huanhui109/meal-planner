"""生成任务区分「首次生成」与「重新生成」

Revision ID: 0005_task_regeneration
Revises: 0004_consumption_identity
Create Date: 2026-09-10

问题: 配额只看"当日创建了多少条任务", 重新生成 (force=true) 也被算进去。
结果用户在同一周里换两次菜单, 第 4 次就被 429 挡住 —— 但重新生成本来
只是常规的编辑动作, 和"开一周新菜单"不是一回事。

加一个 is_regeneration 标记, 让两者走各自的额度 (首次 3 次/日, 重生成 10 次/日)。
老数据默认 0, 即全部算作首次生成, 回填无歧义。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_task_regeneration"
down_revision = "0004_consumption_identity"
branch_labels = None
depends_on = None

TABLE = "menu_generation_task"
COLUMN = "is_regeneration"
INDEX = "ix_menu_task_user_regen"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否为重新生成 (走独立配额, 不占用首次生成额度)",
        ),
    )
    op.create_index(INDEX, TABLE, ["user_id", COLUMN, "created_at"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_column(TABLE, COLUMN)
