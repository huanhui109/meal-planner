"""recipe.is_dish —— 用显式字段挡住"不是一个菜"的条目 (v1.2.0)

为什么加这一列:
    396 道的候选池里混着 61 条不是一道菜的东西 —— 调味品(油泼辣子/炸串酱料)、
    饮品(B52轰炸机/酸梅汤)、甜品(提拉米苏/雪花酥)、半成品加工(速冻水饺/牛油火锅底料)。
    它们的 category 被导入规则强行归成了荤菜/素菜/汤羹/小吃, 于是决策引擎里所有基于
    category 的过滤全部失效: 用户点「饭决」, 屏幕上真的出现过"油泼辣子"。

为什么不直接拿 cuisine 做黑名单:
    导入时列错位, cuisine 列目前装的是**源分类**(调味品/饮品/甜品/半成品加工)。
    这列迟早要清洗成真菜系, 那时基于它的黑名单会静默失效、事故原地复发。
    语义必须写在显式列上 —— 本项目的铁律是: 宁可规则不生效, 也不要生效成错的。

为什么默认 1 而不是 0:
    默认值选的是"放行"。新菜入库时如果一个错判断成非菜, 结果是用户永远吃不到它,
    且没人会发现; 反过来漏判一道, 最坏是多推一次奶茶。两害相权取其轻。

为什么给 TINYINT(1) 但不建索引:
    is_dish 只有两个值, 选择性极差, 加索引 MySQL 也只会全表扫。
    顺带省掉一个坑 —— MySQL 外键错 1553: downgrade 里先 drop_index 再 drop_table
    会因为索引还挂着外键约束而失败, 少建一个对象就少一处出错的地方。

!!! 铁律: 永远追加新号, 不要回填中间号。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_recipe_is_dish"
down_revision = "0016_dish_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipe",
        sa.Column(
            "is_dish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否是一道正经的菜: 0=调味品/饮品/甜品/半成品加工, 不参与「饭决」决策; 1=正常候选",
        ),
    )


def downgrade() -> None:
    op.drop_column("recipe", "is_dish")
