"""V1.2.0 R-16 —— event.layout_version: 让灰度组能直接从事件表里切出来

为什么要单独来一个迁移而不是并进 0018:
    0018 是 R-06/R-07 的埋点基建(会话 + 决策质量), 0019 是 R-16 的灰度归因。
    两件事的验收标准、回滚边界都不同, 挤在一个迁移里将来没人敢只回滚其中一个。

为什么最终还是建了列(当初我给的建议是"不建"):
    建议不建的前提是"layout_version 已经躺在每条事件的 properties 里, JSON_EXTRACT
    就能切"。但 team-lead 拍的是: 前端(尤其还没开工的小程序端)并不稳定地从顶层
    下发这个字段, 只靠 properties 会出现"同一个取法在不同端落不到同一个地方"的情况,
    而灰度结论一旦被当成事实引用, 取不到比取错了还伤。列是不可含糊的事实来源。
    代价是 properties 里的同名 key 短期内还在, 容忍方式是 events.py 里那个和
    session_id 同款的"顶层优先 + 回落 properties"取值, 且同样写死了删除条件。

为什么索引建成 (layout_version, received_at) 而不是只建 layout_version:
    只按 layout_version 查是极低选择性的(只有 v1.1/v1.2 两个值), 单列索引 MySQL
    同样只走全表; 真正的查询形态是"某灰度组在某段时间内", 所以带上 received_at。
    时间口径用服务端 received_at 而不是客户端 ts —— 理由见 models/event.py。

MySQL 坑: downgrade 只 drop_column, 索引随列消失(外键 1553 那条同上)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_event_layout_version"
down_revision = "0018_decision_analytics"
branch_labels = None
depends_on = None

EVENT = "event"


def upgrade() -> None:
    op.add_column(
        EVENT,
        sa.Column(
            "layout_version",
            sa.String(length=20),
            nullable=True,
            comment="首页灰度版本(服务端下发): v1.1/v1.2; 未灰度或未知时为 NULL",
        ),
    )
    # 可空且不加默认值是有意的: 服务端没配置就必须是 NULL, 不能是 'v1.2'。
    # 后端替前端兜底会把"不知道自己分在哪组"的行算进某一组, 灰度结论直接失效。
    op.create_index("ix_event_layout_received", EVENT, ["layout_version", "received_at"])


def downgrade() -> None:
    # ⚠️ 复合索引必须**先显式删**, 不能指望 DROP COLUMN 顺带删掉它。
    # 这条assert是这样填出来的: 第一版只写了 drop_column, 结果 MySQL 并没有把
    # (layout_version, received_at) 这个索引删掉 —— 它把 layout_version 那一列从
    # 索引里摘掉、索引名**原样保留**, 于是 DOWN 之后库里躺着一个叫
    # ix_event_layout_received 的索引, 但它的内容只剩 (received_at), 和已有的
    # ix_event_received_at 完全重复。
    # (MySQL 手册的说法是: 索引里被删的列会被摘掉; 所有列都被删掉时索引才消失。
    #  0010 那条"索引随列消失"的写法只对单列索引成立。)
    # 后果比难看更严重: 索引名被占住, 再 upgrade 时 CREATE INDEX 会报 1061 重复键名。
    # 这里没有外键依赖该索引, 所以不涉及 1553。
    op.drop_index("ix_event_layout_received", table_name=EVENT)
    op.drop_column(EVENT, "layout_version")
