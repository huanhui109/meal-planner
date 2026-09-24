"""V1.2.0 R-10(d) —— decision_log.band_size: 用户真正在几道菜里抽签

为什么单列这一列(而不是继续用 candidate_count 顶着):
    实测晚饭档 candidate_count = 296, 但 `_random_band` 实际返回的抽签带只有 116。
    "通过 `_passes` 的行数"和"用户真的在几道里选"是两件事, 前者会系统性高估选择空间。
    抽签带塌缩时 band_size 会从三位数掉到个位数 —— 比看占比灵敏, 而且**不依赖样本量**
    (占比类判据要凑够样本才敢下结论, 绝对值不用)。J6'/J7' 的分母用它(PRD §C15)。

为什么可空而不是 NOT NULL DEFAULT 0:
    迁移前已有的决策行没有这个测量值。NULL 的语义是"当时没测", 而 0 的语义是
    "抽签带空了" —— 后者是**缺陷信号**(R-10 会据此打 decide_empty_pool 告警)。
    用缺值伪造出一个 0, 等于凭空造了一批告警。所以这里 NULL 与 0 必须分得开,
    任何统计都要先排除 NULL(读法见 decision_metrics.exhaustion_rate 的 coalesce)。

为什么是 0020 而不是并进 0018:
    0018 是 R-06/R-07 的埋点基建, 0019 是 R-16 的灰度列, 0020 是 R-10 的度量列。
    三件事的验收与回滚边界都不同, 挤在一起将来没人敢只回滚其中一个。
    版本号按开工时 `ls versions | sort | tail -1` 动态取, 不写死。

MySQL 坑: 单列索引随列消失, 复合索引不会(会把被删列摘掉、索引名保留) ——
本迁移只有一个可空列且不建索引, 不涉及。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_decision_band_size"
down_revision = "0019_event_layout_version"
branch_labels = None
depends_on = None

DECISION = "decision_log"


def upgrade() -> None:
    op.add_column(
        DECISION,
        sa.Column(
            "band_size",
            sa.Integer(),
            nullable=True,
            comment="实际抽签带大小(_random_band 长度); NULL=当时没测",
        ),
    )


def downgrade() -> None:
    op.drop_column(DECISION, "band_size")
