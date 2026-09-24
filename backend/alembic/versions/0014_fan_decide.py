"""饭决 FAN·DECIDE 决策引擎 (v1.0.0)

新增决策流水与反馈表, 给 recipe / diet_preference 补决策所需字段。

!!! 铁律: 永远追加新号, 不要回填中间号。
在已执行到 0013 的库上新建 0012_* 会插到链中间, upgrade head 永远升不上去。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_fan_decide"
down_revision = "0013_product_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- recipe: 决策需要的品类 / 标签 / 轻食 / 极简做法 ----
    op.add_column("recipe", sa.Column("category", sa.String(length=50), nullable=True,
                                      comment="品类: 荤菜/素菜/汤羹/主食/面食/凉菜/小吃"))
    op.add_column("recipe", sa.Column("main_ingredient", sa.String(length=50), nullable=True,
                                      comment="主料, 判断连续两餐不重样的最小粒度"))
    op.add_column("recipe", sa.Column("tags", sa.String(length=500), nullable=True,
                                      comment="场景标签 JSON 数组"))
    op.add_column("recipe", sa.Column("flavor_tags", sa.String(length=500), nullable=True,
                                      comment="味型标签 JSON 数组"))
    op.add_column("recipe", sa.Column("spice_level", sa.Integer(), nullable=False,
                                      server_default=sa.text("0"), comment="辣度 0-4"))
    op.add_column("recipe", sa.Column("is_light", sa.Boolean(), nullable=False,
                                      server_default=sa.text("0"), comment="轻食: 深夜只从这里挑"))
    op.add_column("recipe", sa.Column("cover_text", sa.String(length=20), nullable=True,
                                      comment="结果卡角标短文本"))
    op.add_column("recipe", sa.Column("quick_steps", sa.Text(), nullable=True,
                                      comment="极简做法 JSON 数组, 3-5 步"))

    # ---- diet_preference: 场景标签 (快手 / 常点外卖 / 愿意炖一小时) ----
    op.add_column("diet_preference", sa.Column("scene_tags", sa.String(length=500), nullable=True,
                                               comment="场景标签 JSON 数组"))

    # ---- decision_log: 每一次「饭决」的流水 ----
    op.create_table(
        "decision_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("dish_name", sa.String(length=200), nullable=False, comment="菜名(冗余, recipe 可删)"),
        sa.Column("dish_category", sa.String(length=50), nullable=True),
        sa.Column("dish_cuisine", sa.String(length=50), nullable=True),
        sa.Column("main_ingredient", sa.String(length=50), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("meal_slot", sa.String(length=20), nullable=False, server_default="dinner"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="local"),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("weather", sa.String(length=20), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True, comment="null未表态/true就这个/false换一个"),
        sa.Column("payload", sa.Text(), nullable=True, comment="决策快照 JSON, GET /decide/last 冷启动秒开用"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_decision_log_user", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], name="fk_decision_log_recipe", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_user_date", "decision_log", ["user_id", "decision_date"])
    op.create_index("ix_decision_user_created", "decision_log", ["user_id", "created_at"])

    # ---- decision_feedback: 决策反馈过程 ----
    op.create_table(
        "decision_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("liked", sa.Boolean(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decision_log.id"], name="fk_decision_fb_decision", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_decision_fb_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_fb_user_created", "decision_feedback", ["user_id", "created_at"])


def downgrade() -> None:
    # 两处要注意:
    # 1) 不要先 drop_index 再 drop_table。MySQL 里 DROP TABLE 会连带删掉索引与外键,
    #    而单独删一个被外键依赖的索引会直接报 1553
    #    (Cannot drop index ... needed in a foreign key constraint) —— 这在 SQLite 上
    #    不会暴露, 只有真跑 MySQL 才炸, 是"SQLite 上能过"的典型假绿。
    # 2) 先删子表 decision_feedback (它的外键指向 decision_log), 顺序反了会报 3730。
    op.drop_table("decision_feedback")
    op.drop_table("decision_log")
    op.drop_column("diet_preference", "scene_tags")
    for column in (
        "quick_steps",
        "cover_text",
        "is_light",
        "spice_level",
        "flavor_tags",
        "tags",
        "main_ingredient",
        "category",
    ):
        op.drop_column("recipe", column)
