"""V2.7 今日饭决「做完了」扣库存

为什么需要这两列:
    今日线 (POST /api/decide) 落库的是 decision_log, **不**创建 menu_item。而原有的
    "标记已做 → 扣库存" 只挂在 menu_item 上 (consume_by_menu_item)。于是"饭决结果 →
    做饭 → 扣冰箱"这条用户心智路径在旧库里是断的。

    补两列把这条链路接上:
    1. decision_log.is_cooked   —— 幂等闸。防止刷新/重复点"做完了"重复扣减, 这是今日线
                                   唯一的去重依据 (周菜单靠 menu_item.is_cooked)。
    2. consumption_record.decision_id —— 今日消耗的流水锚点。menu_item_id 与 decision_id
                                       至多其一非空, 否则今日扣的库存既不可审计也写不了撤销。

两列都是 nullable=False 带 server_default / 可空, 老的 190+ 行决策与消耗流水不受影响。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_decision_cooked"
down_revision = "0022_sync_column_comments"
branch_labels = None
depends_on = None

DECISION = "decision_log"
CONSUMPTION = "consumption_record"


def upgrade() -> None:
    op.add_column(
        DECISION,
        sa.Column(
            "is_cooked",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
            comment="今日饭决是否已做并扣库存",
        ),
    )
    op.add_column(
        CONSUMPTION,
        sa.Column(
            "decision_id",
            sa.Integer(),
            # 显式命名, 与仓库其它迁移的 fk_* 约定一致。
            # 不命名的话 MySQL 会生成 consumption_record_ibfk_N —— 序号取决于该表上
            # 已有几个外键, downgrade 时写死这个名字是不稳的。
            sa.ForeignKey(
                "decision_log.id", name="fk_consumption_decision", ondelete="SET NULL"
            ),
            nullable=True,
            comment="关联的今日饭决决策(今日做饭扣库存时填)",
        ),
    )


def downgrade() -> None:
    """
    ⚠ MySQL 不允许直接删被外键引用的列 —— 报 1828
      "Cannot drop column 'decision_id': needed in a foreign key constraint"。
      必须先删约束，再删列。与 0018 里"外键先于列删除"是同一条规矩。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 按实际查出的约束名删：0023 初版用的是不命名的 sa.ForeignKey()，
    # 已经跑过那一版的库上约束名仍是 MySQL 自动生成的 consumption_record_ibfk_N，
    # 这里写死 fk_consumption_decision 会在那些库上炸。
    for fk in inspector.get_foreign_keys(CONSUMPTION):
        if "decision_id" in (fk.get("constrained_columns") or []):
            op.drop_constraint(fk["name"], CONSUMPTION, type_="foreignkey")
            break

    # MySQL 为外键自动建的索引不随约束一起消失，留着会让 drop_column 报 1553
    for idx in inspector.get_indexes(CONSUMPTION):
        if idx.get("column_names") == ["decision_id"]:
            op.drop_index(idx["name"], table_name=CONSUMPTION)
            break

    op.drop_column(CONSUMPTION, "decision_id")
    op.drop_column(DECISION, "is_cooked")
