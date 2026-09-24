"""菜品场景维度 + LLM 富集流水 (v1.1.0)

为什么要这一版:
    「饭决」回答的是"这一顿吃什么", 而 recipe 表里此前只有"这道菜好不好吃"的字段。
    缺的三个维度直接让决策出错:
      1. cook_minutes 93% 为 NULL → 决策里 `or 30`, 深夜和时间上限过滤形同虚设
      2. 没有"适合餐次" → 早上也能推出红烧肉
      3. 荤素靠菜名字符串猜 → 「鸡蛋」含「鸡」被判成荤

    所以这一版补的是**场景层**字段(meal_slots / meat_type / tools / season),
    外加一张富集流水表, 让兜底大模型的每一次补充都可追溯。

!!! 铁律: 永远追加新号, 不要回填中间号。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_dish_enrichment"
down_revision = "0015_replace_rejected_recipes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- recipe: 场景层字段 ----
    op.add_column("recipe", sa.Column("meal_slots", sa.String(length=100), nullable=True,
                                      comment="适合餐次 JSON 数组: breakfast/lunch/dinner/late_night"))
    op.add_column("recipe", sa.Column("meat_type", sa.String(length=30), nullable=True,
                                      comment="荤型: none/egg_dairy/poultry/red_meat/seafood/mixed"))
    op.add_column("recipe", sa.Column("tools", sa.String(length=200), nullable=True,
                                      comment="所需厨具 JSON 数组: wok/steamer/oven/air_fryer/..."))
    op.add_column("recipe", sa.Column("season", sa.String(length=60), nullable=True,
                                      comment="时令 JSON 数组: spring/summer/autumn/winter"))

    # ---- recipe: 富集追踪 ----
    op.add_column("recipe", sa.Column("enrich_status", sa.String(length=20), nullable=False,
                                      server_default="pending",
                                      comment="富集状态: pending/partial/done/failed"))
    op.add_column("recipe", sa.Column("enriched_at", sa.DateTime(), nullable=True,
                                      comment="最近一次富集时间"))
    op.add_column("recipe", sa.Column("enrich_source", sa.String(length=30), nullable=True,
                                      comment="字段来源: seed/rule/llm/manual"))
    op.add_column("recipe", sa.Column("steps_source", sa.String(length=30), nullable=True,
                                      comment="做法来源: seed/rule/llm/manual"))
    op.create_index("ix_recipe_enrich_status", "recipe", ["enrich_status"])

    # ---- recipe_enrich_log: 富集流水 ----
    op.create_table(
        "recipe_enrich_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True,
                  comment="EXPAND 成功前为 NULL"),
        sa.Column("dish_name", sa.String(length=200), nullable=False, comment="菜名(冗余)"),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="fields",
                  comment="fields/steps/expand"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="ok/skipped/failed"),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="",
                  comment="llm 链里真正用上的客户端名"),
        sa.Column("fields", sa.String(length=300), nullable=True, comment="本次写入的字段名"),
        sa.Column("message", sa.String(length=500), nullable=True, comment="失败原因/备注"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="菜品富集流水: 定时任务无人值守, 过程必须可追溯",
    )
    op.create_index("ix_recipe_enrich_created", "recipe_enrich_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_recipe_enrich_created", table_name="recipe_enrich_log")
    op.drop_table("recipe_enrich_log")
    op.drop_index("ix_recipe_enrich_status", table_name="recipe")
    for col in ("steps_source", "enrich_source", "enriched_at", "enrich_status",
                "season", "tools", "meat_type", "meal_slots"):
        op.drop_column("recipe", col)
