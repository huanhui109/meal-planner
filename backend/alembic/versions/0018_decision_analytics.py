"""V1.2.0 R-06 + R-07 —— 埋点基建: event 加会话列, decision_log 加决策质量六列

为什么是 0018:
    版本号必须动态取(开工时 ls versions | sort | tail -1 = 0017_recipe_is_dish),
    写死就会和别人抢号。`0017` 已归 "recipe.is_dish" 专用, 本迁移只能追加在它后面。

为什么不加 decision_event 表:
    PRD §6 的 R-06 原文写的是"建 decision_event 表", 但那是在没确认过后端现状时
    下的判断。实际上 event 表(T2.6 就有)已经把埋点该有的脏活全做完了 —— 匿名上报、
    单批 1-50 条、单条 5KB 拦截、失败静默。再来一张语义完全相同的表, 只会让每条
    漏斗 SQL 多一层 union, 而且两边 session_id 一旦不同步就无法对账。
    结论: 复用 event, 只补两列。**这是有意的偏离, 不是漏做。**

六列为什么不留在 payload JSON 里:
    payload 是给前端回放界面用的自由格式文档。拿它当事实来源等于把数据指标建在
    UI 快照上 —— 前端改个渲染字段, 指标口径跟着漂。更直接的理由是查不了:
    "多少次决策放宽了条件"原本只能 LIKE '%"relaxed": true%' 全表扫。

⚠️ 历史数据口径:
    执行本迁移前已有的 190 行 decision_log 是联调/压测数据(数据依据 §5.6)。
    新列给的是 DEFAULT 0, 表示"列非空", **不表示当年没放宽**。所有统计必须带
    created_at >= <上线时间> 过滤, 读法统一走 app/services/decision_metrics.py。

MySQL 坑记在这里, 免得下一个人再踩:
    - 列必须给长度 / 类型细节, 否则 MySQL 起来的是另一回事
    - downgrade 只 drop_column, 不碰索引: MySQL 1553 会因为外键还挂索引而拒绝
    - JSON 列没有字面量默认值, 只能用 NULL + nullable
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_decision_analytics"
down_revision = "0017_recipe_is_dish"
branch_labels = None
depends_on = None

EVENT = "event"
DECISION = "decision_log"


def upgrade() -> None:
    # ------------------------------------------------------------------ R-06 event
    op.add_column(
        EVENT,
        sa.Column(
            "session_id",
            sa.String(length=36),
            nullable=True,
            comment="会话 ID (前端 UUIDv4), 串联一次决策全链路事件",
        ),
    )
    op.add_column(
        EVENT,
        sa.Column(
            "decision_id",
            sa.Integer(),
            nullable=True,
            comment="关联的决策流水 id, 决策前的事件为空",
        ),
    )
    op.create_foreign_key(
        "fk_event_decision", EVENT, DECISION, ["decision_id"], ["id"], ondelete="SET NULL"
    )
    # 会话时间线。第二列用 received_at 而不是 ts: 客户端时钟可能错, 会话内排序必须可信。
    # 它的左前缀 session_id 已经覆盖"只按 session_id 查", 不再单独建一个一样的单列索引
    op.create_index("ix_event_session_received", EVENT, ["session_id", "received_at"])
    # 反查某次决策前后发生了什么 (J5 决策→开做转化要 join)
    op.create_index("ix_event_decision_id", EVENT, ["decision_id"])

    # ---------------------------------------------------------------- R-07 decision_log
    op.add_column(
        DECISION,
        sa.Column(
            "session_id",
            sa.String(length=36),
            nullable=True,
            comment="会话 ID (前端 UUIDv4), 与 event.session_id 同源",
        ),
    )
    op.add_column(
        DECISION,
        sa.Column(
            "reroll_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="出此结果前已点了几次换一个",
        ),
    )
    op.add_column(
        DECISION,
        sa.Column(
            "relaxed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否放宽了候选条件",
        ),
    )
    op.add_column(
        DECISION,
        sa.Column(
            "relaxed_level",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="放宽级别 0=未放宽, 1-6 见 R-10",
        ),
    )
    op.add_column(
        DECISION,
        sa.Column(
            "candidate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="放宽前候选池大小",
        ),
    )
    op.add_column(
        DECISION,
        sa.Column(
            "filters_snapshot",
            sa.JSON(),
            nullable=True,
            comment="本次决策的过滤条件快照",
        ),
    )
    op.create_index("ix_decision_session", DECISION, ["session_id"])
    # J3 按餐次切片 (全时段 ≤8% / 夜宵 ≤20% 是两条线, 不能混)
    op.create_index("ix_decision_slot_created", DECISION, ["meal_slot", "created_at"])


def downgrade() -> None:
    # MySQL 1553: 外键依赖的索引不能单独 drop, 所以这里只 drop_column,
    # 索引随列一起消失。反过来 (先 drop_index 再 drop_column) 必炸。
    # 外键也先于列删除: decision_id 上的 FK 挂着索引, 留着会让 drop_column 报 1553。
    op.drop_constraint("fk_event_decision", EVENT, type_="foreignkey")

    op.drop_index("ix_decision_slot_created", table_name=DECISION)
    op.drop_column(DECISION, "filters_snapshot")
    op.drop_column(DECISION, "candidate_count")
    op.drop_column(DECISION, "relaxed_level")
    op.drop_column(DECISION, "relaxed")
    op.drop_column(DECISION, "reroll_index")
    op.drop_column(DECISION, "session_id")

    op.drop_index("ix_event_session_received", table_name=EVENT)
    op.drop_column(EVENT, "decision_id")
    op.drop_column(EVENT, "session_id")
    # ix_event_decision_id 随 decision_id 列消失, ix_decision_session 随 session_id 列消失
