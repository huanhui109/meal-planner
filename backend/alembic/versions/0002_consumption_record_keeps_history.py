"""consumption_record 保留消耗流水

Revision ID: 0002_consumption_record
Revises: 0001_init
Create Date: 2026-09-10

问题: fridge_inventory_id 原本是 NOT NULL + ON DELETE CASCADE。库存扣空后批次行会被
删除, MySQL 会顺着外键把刚写入的 consumption_record 一起级联删除, 导致消耗流水丢失
(SQLite 默认不启用外键, 所以本地跑 SQLite 时看不出来)。

改为可空 + ON DELETE SET NULL: 批次行可以正常删除, 但历史流水保留下来。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_consumption_record"
down_revision = "0001_init"
branch_labels = None
depends_on = None

TABLE = "consumption_record"
COLUMN = "fridge_inventory_id"
TARGET = "fridge_inventory"
NEW_FK = "fk_consumption_record_inventory"

FIND_FK = sa.text(
    """
    SELECT CONSTRAINT_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = :table
      AND COLUMN_NAME = :column
      AND REFERENCED_TABLE_NAME = :target
    """
)


def _existing_fk_name() -> str | None:
    """查出 0001 建表时自动生成的外键名 (各实例名字可能不同)。

    离线模式 (alembic upgrade --sql) 下没有真实连接, 这里返回 None,
    生成的脚本会少一句 DROP FOREIGN KEY, 仅供肉眼检查用。
    """
    bind = op.get_bind()
    if bind is None or bind.dialect.name != "mysql":
        return None
    result = bind.execute(FIND_FK, {"table": TABLE, "column": COLUMN, "target": TARGET})
    if result is None:
        return None
    return result.scalar()


def upgrade() -> None:
    existing = _existing_fk_name()
    if existing:
        op.drop_constraint(existing, TABLE, type_="foreignkey")
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.Integer(),
        nullable=True,
        existing_nullable=False,
    )
    op.create_foreign_key(
        NEW_FK, TABLE, TARGET, [COLUMN], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(NEW_FK, TABLE, type_="foreignkey")
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.Integer(),
        nullable=False,
        existing_nullable=True,
    )
    op.create_foreign_key(
        None, TABLE, TARGET, [COLUMN], ["id"], ondelete="CASCADE"
    )
