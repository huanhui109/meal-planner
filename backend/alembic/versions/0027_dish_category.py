"""菜品类别法典: 字典表 + recipe 单值类别 + 家人口味单选

!!! 铁律: 永远追加新号, 不要回填中间号。
为什么不用 recipe.cuisine: 导入时列错位, 那一列装的是源分类(荤菜/主食/早餐/甜品),
没有菜系语义; 项目已把 score_cuisine 钉成 0。这里另起一个互斥大类维度。

为什么 recipe 列 NOT NULL + 默认 other: 「每道菜只归属一个类别」靠单值非空列保证,
新菜未经回填先落 other, 由 scripts/backfill_dish_category.py 按规则补齐;
运行时 load_meal_catalog 还会对 other 做一次无副作用的规则兜底(不写库)。
不建指向字典表的外键: 测试夹具会 TRUNCATE 所有表, FK 会让造数据直接失败。

downgrade 顺序: 先 drop_index 再 drop_column(复合索引不会随列消失)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_dish_category"
down_revision = "0026_inbound_bridge"
branch_labels = None
depends_on = None

# 与 shared/dish-category.ts 的 DISH_CATEGORIES 逐行对应,
# 被 backend/tests/unit/test_dish_category_parity.py 静态比对。
SEED_CATEGORIES = [
    {"code": "chinese", "name": "中餐", "description": "中式家常、川湘粤鲁等地方菜与中式主食", "sort_order": 1},
    {"code": "western", "name": "西餐", "description": "欧美菜式、烘焙、沙拉与西式主食", "sort_order": 2},
    {"code": "japanese_korean", "name": "日韩", "description": "日式与韩式料理", "sort_order": 3},
    {"code": "southeast_asian", "name": "东南亚·南亚", "description": "泰越新马印尼与印度等南亚料理", "sort_order": 4},
    {"code": "other", "name": "其他", "description": "融合菜、饮品甜品与暂未归类的条目", "sort_order": 5},
]


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "dish_category",
        sa.Column("code", sa.String(32), primary_key=True, comment="类别 code, 与 shared/dish-category.ts 一致"),
        sa.Column("name", sa.String(50), nullable=False, comment="展示名称"),
        sa.Column("description", sa.String(200), nullable=True, comment="口径说明"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="展示顺序"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否启用"),
        *timestamps(),
    )
    op.bulk_insert(sa.table(
        "dish_category",
        sa.column("code", sa.String(32)),
        sa.column("name", sa.String(50)),
        sa.column("description", sa.String(200)),
        sa.column("sort_order", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
    ), [{**row, "enabled": True} for row in SEED_CATEGORIES])

    op.add_column("recipe", sa.Column(
        "dish_category_code", sa.String(32), nullable=False,
        server_default=sa.text("'other'"),
        comment="菜品类别(互斥单值): chinese/western/japanese_korean/southeast_asian/other; 见 dish_category 字典表",
    ))
    # 索引名与 SQLAlchemy 的 index=True 默认命名保持一致, 否则 autogenerate 会误判漂移
    op.create_index("ix_recipe_dish_category_code", "recipe", ["dish_category_code"])

    # NULL / 空串 = 不限类别。不限只是不过滤候选, 方案内类别一致仍是硬规则。
    op.add_column("diet_preference", sa.Column(
        "dish_category", sa.String(32), nullable=True,
        comment="家人口味: 菜品大类(单选互斥), NULL=不限; 值见 dish_category 字典表",
    ))


def downgrade() -> None:
    op.drop_column("diet_preference", "dish_category")
    op.drop_index("ix_recipe_dish_category_code", table_name="recipe")
    op.drop_column("recipe", "dish_category_code")
    op.drop_table("dish_category")
