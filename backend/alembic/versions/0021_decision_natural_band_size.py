"""V1.2.0 R-10(d2) —— decision_log.natural_band_size: 分数带内的真带大小

为什么在 band_size 之外还要这一列:
    `_random_band` 在真带不足 `random_min_choices` 时会**按分数补齐**到下限, 于是
    `band_size >= random_min_choices` 恒真 —— 实测真带只剩 1 道时 band_size 仍是 3。
    塌缩被 padding 完全掩盖, 任何 "band_size >= N" 形状的判据都会在池子塌掉时**假绿**。
    塌缩必须看"不含补齐"的这个数。

两个数的分工(别互相替代):
    band_size            = 用户实际能抽到的道数(含补齐)。回答"换一个会不会横跳" ——
                           补齐出来的菜也是真能拿到的, 所以这一列对那个问题是对的。
    natural_band_size    = 分数带内(score >= best - random_band)的真带。回答
                           "池子塌没塌"。塌缩判据用它。

为什么可空: 与 band_size 同一个规矩 —— NULL = 当时没测, 0 = 真带空了(缺陷信号)。
缺值不能伪造出 0, 否则等于凭空造告警。同理, 统计塌缩时**不要**把它 coalesce 回
candidate_count, 那样又把"通过了过滤"当成"真的能选", 高估回来。

版本号按开工时 `ls versions | sort | tail -1` 动态取(0018/0019/0020 都已占用)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_decision_natural_band_size"
down_revision = "0020_decision_band_size"
branch_labels = None
depends_on = None

DECISION = "decision_log"


def upgrade() -> None:
    op.add_column(
        DECISION,
        sa.Column(
            "natural_band_size",
            sa.Integer(),
            nullable=True,
            comment="分数带内真带大小(不含补齐); NULL=当时没测",
        ),
    )


def downgrade() -> None:
    op.drop_column(DECISION, "natural_band_size")
