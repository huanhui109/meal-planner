"""AI 候选补全的可追溯字段: 现实依据 + 生成来源标记

这条迁移只做一件事: 让「由 AI 按缺口补进候选池」的菜**可追溯**，而不是和人工
导入的菜混在一起无法区分。

背景（为什么需要它）:
饭决的底线是「禁止杜撰」—— 不得编造不存在的菜名与做法。用户只描述大致需求
（如「想吃点暖胃的汤」）而候选池覆盖不足时，允许 AI 补 3 道**现实中确实存在**
的菜进候选池，但必须留下证据，否则「补全」和「凭空生成」在库里长得一模一样。

新增列:
- ``reality_basis``: 该菜名与做法在现实中成立的依据（菜系归属、通行做法要点、
  典型配料）。空值 = 非 AI 补全路径写入的行，不做任何假设。
- ``generated_for``: 触发补全的用户原始需求摘要（截断）。空值同上。

刻意不建唯一约束: 同名菜可能来自不同来源（人工导入 / AI 补全），去重由服务层按
normalize_dish_name 判断；加 UNIQUE 会让既有重复数据无法迁移，也会让「补全失败
但已写日志」的路径抛 IntegrityError。

downgrade 顺序: 先 drop_index 再 drop_column（复合索引不会随列消失，教训见 0019）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_recipe_provenance"
down_revision = "0027_dish_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipe", sa.Column(
        "reality_basis", sa.String(500), nullable=True,
        comment="AI 补全时的现实依据(菜系归属/通行做法要点); 空=非补全写入",
    ))
    op.add_column("recipe", sa.Column(
        "generated_for", sa.String(200), nullable=True,
        comment="触发 AI 补全的用户需求摘要; 空=非补全写入",
    ))
    # 只索引补全出来的行，便于审计与「这条是 AI 补的」查询；NULL 不参与。
    op.create_index(
        "ix_recipe_generated_for", "recipe", ["generated_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_generated_for", table_name="recipe")
    op.drop_column("recipe", "generated_for")
    op.drop_column("recipe", "reality_basis")
