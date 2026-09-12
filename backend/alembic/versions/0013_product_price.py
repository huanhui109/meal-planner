"""商品价格历史表 (audit T4.1 V3.0)

记录每个商品的历次抓到的价格点 (price_history)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_product_price"
down_revision = "0012_invite"
branch_labels = None
depends_on = None

TABLE = "product_price"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "captured_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=50), nullable=True, server_default="scheduler"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"], name="fk_product_price_product", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 按商品 + 时间: 价格趋势查询常用
    op.create_index("ix_product_price_product_captured", TABLE, ["product_id", "captured_at"])


def downgrade() -> None:
    # MySQL 要求先删外键再删索引 (否则报 1553: index needed in a FK constraint)
    op.drop_constraint("fk_product_price_product", TABLE, type_="foreignkey")
    op.drop_index("ix_product_price_product_captured", table_name=TABLE)
    op.drop_table(TABLE)
