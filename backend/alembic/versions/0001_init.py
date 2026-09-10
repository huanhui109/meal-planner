"""init schema - 17 张表基线

Revision ID: 0001_init
Revises:
Create Date: 2026-09-10

手写基线以保证可审计: 不用 Base.metadata.create_all, 避免以后改模型导致
全新库与已迁移库结构漂移。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

MYSQL_TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
NOW = sa.text("CURRENT_TIMESTAMP")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("open_id", sa.String(length=100), nullable=False, comment="飞书 open_id"),
        sa.Column("union_id", sa.String(length=100), nullable=True, comment="飞书 union_id"),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("open_id"),
        sa.UniqueConstraint("union_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "household",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, comment="家庭人数"),
        sa.Column("meals_per_day", sa.Integer(), nullable=False, comment="每日餐次"),
        sa.Column("kitchen_equipments", sa.String(length=500), nullable=True, comment="厨房设备 JSON"),
        sa.Column("weekday_cook_minutes", sa.Integer(), nullable=False),
        sa.Column("weekend_cook_minutes", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "diet_preference",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cuisines", sa.String(length=500), nullable=True, comment="偏好菜系 JSON"),
        sa.Column("spice_level", sa.Integer(), nullable=False),
        sa.Column("flavor_preference", sa.String(length=100), nullable=True),
        sa.Column("staple_preference", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "allergy_restriction",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("allergens", sa.String(length=500), nullable=True, comment="过敏源 JSON"),
        sa.Column("avoid_ingredients", sa.Text(), nullable=True, comment="忌口食材 JSON"),
        sa.Column("dietary_restrictions", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "health_goal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_type", sa.String(length=50), nullable=True),
        sa.Column("daily_calories", sa.Integer(), nullable=True),
        sa.Column("protein_pct", sa.Integer(), nullable=True),
        sa.Column("carb_pct", sa.Integer(), nullable=True),
        sa.Column("fat_pct", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "budget",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("weekday_daily_budget", sa.Float(), nullable=False, comment="工作日日预算"),
        sa.Column("weekend_daily_budget", sa.Float(), nullable=False, comment="周末日预算"),
        sa.Column("weekly_cap", sa.Float(), nullable=True, comment="周预算上限"),
        sa.Column("min_meal_budget", sa.Float(), nullable=True, comment="单餐预算下限"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "ingredient",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("standard_unit", sa.String(length=20), nullable=True),
        sa.Column("reference_price", sa.Float(), nullable=True, comment="参考单价(元/标准单位)"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "recipe",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cuisine", sa.String(length=50), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("cook_minutes", sa.Integer(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("carb_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "recipe_ingredient",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True, comment="用量(标准单位)"),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("amount_text", sa.String(length=50), nullable=True, comment="原始用量文本"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_platform", sa.String(length=50), nullable=False),
        sa.Column("sku_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("price_changed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_platform", "sku_id", name="uq_product_platform_sku"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "product_mapping",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingredient_id", "product_id", name="uq_mapping_ingredient_product"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False, comment="周起始日期(周一)"),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_menu_user_week", "menu", ["user_id", "week_start_date"])
    op.create_index("ix_menu_user_status", "menu", ["user_id", "status"])

    op.create_table(
        "menu_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("meal_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
        sa.Column("is_cooked", sa.Boolean(), nullable=False),
        sa.Column("cook_mode", sa.String(length=20), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=True, comment="预估成本(元)"),
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["menu_id"], ["menu.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_menu_item_menu_date", "menu_item", ["menu_id", "meal_date"])

    op.create_table(
        "menu_generation_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=True),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("request_payload", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_id"], ["menu.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index("ix_menu_task_status_created", "menu_generation_task", ["status", "created_at"])
    op.create_index("ix_menu_task_user_created", "menu_generation_task", ["user_id", "created_at"])

    op.create_table(
        "fridge_inventory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "consumption_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fridge_inventory_id", sa.Integer(), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["fridge_inventory_id"], ["fridge_inventory.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_item.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )

    op.create_table(
        "purchase_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("purchased_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        **MYSQL_TABLE_ARGS,
    )


def downgrade() -> None:
    for table in (
        "purchase_record",
        "consumption_record",
        "fridge_inventory",
        "menu_generation_task",
        "menu_item",
        "menu",
        "product_mapping",
        "product",
        "recipe_ingredient",
        "recipe",
        "ingredient",
        "budget",
        "health_goal",
        "allergy_restriction",
        "diet_preference",
        "household",
        "user",
    ):
        op.drop_table(table)
