"""consumption_record 记下"消耗的是什么"

Revision ID: 0004_consumption_identity
Revises: 0003_v2_today
Create Date: 2026-09-10

「标记已做」要能撤销 (5 秒内 Toast 可回滚)。扣减时库存批次行一旦被扣空就会被删除,
流水里只剩 fridge_inventory_id = NULL, 没法还原。

所以给流水补两个字段: ingredient_id 与 unit。这样撤销时即使批次行没了, 也能按
"什么食材 / 多少 / 什么单位" 原样补回一条库存行。

老数据回填: 能连上批次行的按批次行补, 补不上的保持 NULL (流水仍然保留)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_consumption_identity"
down_revision = "0003_v2_today"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consumption_record",
        sa.Column("ingredient_id", sa.Integer(), nullable=True, comment="食材"),
    )
    op.add_column(
        "consumption_record",
        sa.Column("unit", sa.String(length=20), nullable=True, comment="消耗时的单位"),
    )
    op.create_foreign_key(
        "fk_consumption_record_ingredient",
        "consumption_record",
        "ingredient",
        ["ingredient_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 尽力回填: 批次行还在的, 顺着批次行把食材与单位补上
    op.execute(
        sa.text(
            """
            UPDATE consumption_record AS cr
            JOIN fridge_inventory AS fi ON fi.id = cr.fridge_inventory_id
            SET cr.ingredient_id = fi.ingredient_id,
                cr.unit = fi.unit
            WHERE cr.ingredient_id IS NULL
            """
        )
    )


def downgrade() -> None:
    # 同 0003: 索引/外键互相占用时 MySQL 会报 errno 1553, 先删外键再删列
    op.drop_constraint("fk_consumption_record_ingredient", "consumption_record", type_="foreignkey")
    op.drop_column("consumption_record", "unit")
    op.drop_column("consumption_record", "ingredient_id")
