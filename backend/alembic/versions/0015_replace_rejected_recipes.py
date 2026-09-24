"""换一道去重: menu_item 记住本餐已经换掉过的菜

「换一道」的排除集合原本只来自「当前菜单里现存的菜名」, 于是 A 换成 B 之后 A 就从
集合里消失了, 下一次打分 A 又变成高分候选 —— 表现为在两道菜之间来回横跳。

加一列记下本餐被换掉的菜谱 id, 打分时一并排除, 保证每次换出来的都是没上过的菜。

!!! 铁律: 永远追加新号, 不要回填中间号。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_replace_rejected_recipes"
down_revision = "0014_fan_decide"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_item",
        sa.Column(
            "rejected_recipe_ids",
            sa.Text(),
            nullable=True,
            comment="本餐被「换一道」换掉的菜谱 id JSON 数组, 避免来回横跳",
        ),
    )


def downgrade() -> None:
    op.drop_column("menu_item", "rejected_recipe_ids")
