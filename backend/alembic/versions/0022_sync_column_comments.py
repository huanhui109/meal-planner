"""V1.2.0 收尾 —— 同步三处已经漂掉的列注释 (只改注释, 不动类型/数据)

为什么要单独一个迁移改注释:
    列注释是**连库看数的人唯一能看到的设计口径**, 而它是在 add_column 那一刻写死的,
    后来在模型里改注释并不会跟着变。现在库里躺着三处与代码不一致的注释:

    1. `decision_log.relaxed_level` 库里写"1-6 见 R-10", 实际是 **5 档(1-4)** ——
       6 档是早期版本的分法。看到"6"的人会把 J3 的深度放宽门槛画在 3(那个口径下
       是"松 main_ingredient"), 而正确的门槛是 RELAX_LEVEL_CATEGORY_SPREAD = 2。
       门槛画错一档不会报错, 只会让枯竭率长期偏低然后被当成"改版有效"。
    2. `decision_log.candidate_count` 缺了"通过 _passes 的行数"这半句 —— 少了它,
       这个数会被当成"用户实际能选的道数", 而它系统性高估(晚饭档 296 vs 抽签带 116)。
       真正的选择空间看 band_size。
    3. `event.ts` 只在模型里写了"指标请用 received_at", 库里没有 —— 客户端时间不可信
       这条口径必须写在最容易被看见的地方, 否则 DAU 会被拿 ts 算。

为什么用裸 SQL 而不是 alter_column:
    MySQL 的 CHANGE COLUMN 要把列定义整条重写, 稍不留神就会把 server_default 之类
    的现有属性改掉。这里只动 COMMENT, MODIFY COLUMN 写清楚完整定义最不容易出意外。

🔴 迁移号有 32 字符硬上限 (本次踩出来的):
    alembic_version.version_num 是 **varchar(32)**, 而 DDL 是非事务的 —— 结果是
    ALTER 全部执行成功、最后 UPDATE alembic_version 时报错 1406
    "Data too long for column 'version_num'", 于是**注释已经改了, 版本号还停在上一版**,
    再跑一次就会重复执行 ALTER(幂等, 但不该出现)。
    所以本迁移最初那版名字 0022_sync_analytics_column_comments (37 字符) 是无效的,
    现改为 25 字符。**后来的人取迁移名时先数一下长度。**

可回滚: downgrade 把三条注释恢复成迁移前的原样。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ⚠️ 长度必须 <= 32 字符, 见上面 docstring 的 1406 事故
revision = "0022_sync_column_comments"
down_revision = "0021_decision_natural_band_size"
branch_labels = None
depends_on = None

# (表名, 列名, 完整列定义, 新注释)
COLUMNS = (
    (
        "decision_log",
        "relaxed_level",
        "int NOT NULL DEFAULT 0",
        "放宽级别 0=未放宽, 1-4 见 R-10 (共 5 档); 门槛一律引用 RELAX_LEVEL_* 常量",
    ),
    (
        "decision_log",
        "candidate_count",
        "int NOT NULL DEFAULT 0",
        "放宽前候选池大小(通过 _passes 的行数); 会高估选择空间, 实际抽签带看 band_size",
    ),
    (
        "event",
        "ts",
        "bigint NOT NULL",
        "客户端 Unix 毫秒时间戳 (不可信, 指标一律用服务端 received_at)",
    ),
)

# 迁移前的原注释, downgrade 用它恢复
OLD_COMMENTS = (
    ("decision_log", "relaxed_level", "放宽级别 0=未放宽, 1-6 见 R-10"),
    ("decision_log", "candidate_count", "放宽前候选池大小"),
    ("event", "ts", "客户端 Unix 毫秒时间戳"),
)


def _modify(table: str, column: str, definition: str, comment: str) -> None:
    op.execute(
        sa.text(
            f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` {definition} COMMENT :comment"
        ).bindparams(comment=comment)
    )


def _definition_of(table: str, column: str) -> str:
    return next(d for t, c, d, _ in COLUMNS if t == table and c == column)


def upgrade() -> None:
    for table, column, definition, comment in COLUMNS:
        _modify(table, column, definition, comment)


def downgrade() -> None:
    for table, column, comment in OLD_COMMENTS:
        _modify(table, column, _definition_of(table, column), comment)
