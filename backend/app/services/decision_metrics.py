"""V1.2.0 判据的读取口 —— 会话时间线 + J3 候选枯竭率

为什么要有这个文件:
    R-06/R-07 往 event / decision_log 里加的列本身不产生价值, 能查出来才产生价值。
    V1.2.0 的判据读法收口在本文件(会话时间线 / J3 + J6'/J7' / 抽签带宽度三条),
    免得每个人自己写 SQL 又把 relaxed 抠回 JSON 里去 —— 那种写法在本版本的
    验收里是算不过去的。

⚠️ 所有查询都必须带 since:
    迁移前已有的 190 行是联调/压测数据 (数据依据 §5.6), 六列新值落到 0 只是
    "列非空"的默认值, 不是"当时没放宽"。不带 created_at 过滤会把 J3 分母灌水。

J3 的口径变了, 别再按旧的算:
    旧口径 relaxed=true 只包含"第 2 级松 cook_cap"; R-10 之后每档都写级别, 于是
    "任一放宽"这个口径前后不可比。现在 J3 = relaxed_level >= 2 的决策数 ÷ 总决策数
    (>= 2 = 松到 category 打散, 即"开始牺牲多样性")。任一放宽降级为 J3b 观测项,
    不设目标。这里的 2 必须是 RELAX_LEVEL_CATEGORY_SPREAD 而不是字面量。

两个池子读数**不许合成一个** (PRD 行动项 12y, 我上一版就是合成的那个, 已改判):
    candidate_count      = 放宽前通过 `_passes` 的行数 → 回答"会不会筛不出菜",
                           **J6' / J7' 用它** (本模块的 `exhaustion_rate()`)。
    natural_band_size    = 分数带内真带大小 → 回答"用户实际在几道里抽",
                           由 **`band_width_p10()` 单独看**, 且**只记录不判定**。

    曾经用 `COALESCE(band_size, candidate_count)` 把两者糊成一列, 后果是
    「池子够、但带塌了」这一类失败**彻底隐身** —— 而它正是这一整版在修的东西
    (meal_slots 塌到 9 道、早餐塌到 14 道、R-09 归一化后 60 → 3, 全是池子没小、
    带崩了)。判据看不见它, 修好的 bug 就没有任何监控。
    两种失败 = 两条判据, 不是一条判据的两个数据入口。

两条通用护栏 (改判据前先看这两条, 它们和 padding 那段是同一类东西):
    1. 判据不能被**恒真**的读数绑架 (band_size 被 padding 保底 → 恒 >= 3,
       见 `band_width_p10()`)。
    2. 判据不能被**历史空壳行**绑架 (candidate_count 的 190 个 0 → P10 恒 0、
       "< 8 占比"恒 100%, 判据上线首日恒失败)。护栏只在 PRD 里是不够的 ——
       下一个改判据的人不会翻 PRD, 所以过滤条件必须写在函数里。

时间口径: 一律 received_at (服务端), 不用 event.ts (客户端), 详见 models/event.py。
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Dict, List, Tuple

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import DecisionLog
from app.models.event import Event
from app.services.decision_service import POOL_MIN, RELAX_LEVEL_CATEGORY_SPREAD

# J3 定的"深度放宽"门槛: 到这一级意味着开始牺牲多样性(cook_cap 之后那档),
# 用户能感知到"给的不是它要的东西"。
#
# 必须引用常量名而不是写数字: J3 的门槛这轮漂过三次 —— 旧口径 relaxed=true
# → 6 档时的 3 → 5 档时的 2。每次都是"某个数字曾经对过", 然后阶梯一改它就变成
# 指着错误档位的沉默错误(现在写 3 指的就是"松 main_ingredient", 偏严两档)。
# 引用之后阶梯再调, 本文件一行都不用动。
DEEP_RELAXATION_LEVEL = RELAX_LEVEL_CATEGORY_SPREAD

# 一个会话最多回放这么多条事件 —— 埋点是 fire-and-forget, 挡住异常重试刷屏的情况
MAX_TIMELINE_ROWS = 500

# 占比类判据的最小样本量 (PRD 行动项 12i, 数析定的: n=60 时 J7' 的 95% CI ≈ ±5.5pp,
# 真实 10% 也会被判成"≤5% 通过")。样本不够时只作观测、不许下结论 ——
# 夜宵档流量小攒得慢, 没有这道闸它会长期假绿, 而且假绿看起来像"改版没问题"。
#
# ⚠️ **禁止跨判据复用本常量** —— 它只适用于本模块的 J6' / J7'。
# 各判据的下限在 PRD §5.6 里是逐条定的, **并不相同**:
#   J5 分母"采纳数 ≥100"、J3 夜宵子样本 ≥100、占比类下钻默认 ≥30、
#   J1 是"会话 ≥200 且 ≥30 个独立用户"。
# 将来有判据要接进本模块时, 把它改成 {"J6'": 200, "J7'": 200, ...} 这样的字典,
# 缺省再取 200 —— 在此之前不要把 J3 之类的下限往这个常量上凑。
MIN_SAMPLE_SIZE = 200

# J6' / J7' 的水位线 —— 引用引擎常量 POOL_MIN(=8) 而不是写 8:
# 它和 DEEP_RELAXATION_LEVEL 是同一类东西, "某个数字曾经对过"然后被上游改动
# 悄悄废掉。这里引用之后, 引擎调水位线本文件一行都不用动。
#   J6' = candidate_count 的 P10 >= 它 (夜宵)
#   J7' = candidate_count < 它 的占比 <= 5% (分档)
POOL_MIN_THRESHOLD = POOL_MIN

# 「只记录、不判定」的显式取值 —— 见 band_width_p10()。
# 报表侧的规矩是 verdict != "ok" 就显示"暂不判定"(PRD §5.6), 所以这里必须是
# 一个**不等于 ok** 的值, 且不能省略这个键: 键一省略, 报表会把它当成通过。
#
# ⚠️ 但文案不能照抄"样本不足": 这里是**阈值还没定**, 样本可能是够的。
#    显示"样本不足"会把"缺阈值"误报成"缺流量", 于是有人去等流量而不是去定阈值 ——
#    这两件事的下一步动作完全不同。record_only 的文案应是「阈值未定、仅观测」。
RECORD_ONLY = "record_only"


async def session_timeline(
    db: AsyncSession, session_id: str, limit: int = MAX_TIMELINE_ROWS
) -> List[Dict[str, Any]]:
    """一个会话的完整事件序列 —— 回答"这一次用户到底经历了什么"

    按 received_at 排序而不是 ts: 客户端时间可能错误, 会话内部顺序错了之后
    "先看筛选再出结果"会被读成反的, 序列分析就没意义了。

    decision_id 一并带出来, 方便把 event 序列和 decision_log 那一行对齐
    (放宽级别 / 候选池大小在 decision_log 上)。
    """
    stmt = (
        select(
            Event.id,
            Event.event_name,
            Event.decision_id,
            Event.properties,
            Event.received_at,
            Event.ts,
        )
        .where(Event.session_id == session_id)
        .order_by(Event.received_at.asc(), Event.id.asc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": r.id,
            "event_name": r.event_name,
            "decision_id": r.decision_id,
            "properties": _loads(r.properties),
            # 服务端时间是唯一可信的时间; ts 保留给上报延迟校正
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "client_ts": r.ts,
        }
        for r in rows
    ]


async def exhaustion_rate(
    db: AsyncSession, since: datetime, until: datetime | None = None
) -> Dict[str, Any]:
    """J3 深度放宽率 + J6'/J7' 候选池水位 —— 总览 + 按餐次切片

    统计口径 (两条硬要求, 抄 SQL 时必须一起抄):
        1. **仅包含 candidate_count > 0 的决策** —— 空壳行排除 (12x, 理由见代码内注释)。
        2. **池子读数只用 `candidate_count`** —— 不再 COALESCE 抽签带 (12y)。
           "会不会筛不出菜" 与 "用户实际在几道里抽" 是**两种失败**, 后者归
           `band_width_p10()`。糊成一列会让「池子够、但带塌了」隐身。

    为什么必须分餐次: J3 的目标是「全时段 ≤8%, 夜宵 ≤20%」两条不同的线。
    夜宵放宽本来就是设计上允许的 (is_light=1 只有 35 道), 混在一起看会把
    夜宵的问题平均到全时段里, 或者反过来被夜宵拉爆全时段。

    等效的裸 SQL (给直接连库的人)::

        SELECT meal_slot,
               COUNT(*) AS decisions,
               SUM(CASE WHEN relaxed_level >= 2 THEN 1 ELSE 0 END) AS deep_relaxed,
               ROUND(AVG(relaxed_level), 3) AS avg_level,
               MIN(candidate_count)  AS min_candidates,
               SUM(candidate_count < 8) AS below_pool_min
        FROM decision_log
        WHERE created_at >= '<上线时间>'      -- 190 行压测数据在上线时间之前, 必须过滤
          AND candidate_count > 0             -- 见上: 只滤"没量过池子", 不滤"量出来是 0"
        GROUP BY meal_slot;

        -- P10 = nearest-rank(排序后第 ceil(0.1*n) 小的那个值), MySQL 没有可移植的
        -- percentile 聚合, 由本函数在 Python 里算(见 `_percentile`)。
        -- SQL 里的 8 = POOL_MIN, 本文件引用的是常量 POOL_MIN_THRESHOLD。

    ⚠️ 口径声明 (**复制这段 SQL 做别的报表时必须一起复制**):
        「统计口径仅包含 candidate_count > 0 的决策, 池子读数只用 candidate_count」。
        不写这句, 有人把 SQL 抄去做另一个报表就会漏掉过滤 —— 本轮已经因为"SQL 被
        复用时丢了限定"栽过一次 (R-06 验收⑤ 的 received_at >= 上线时间)。

    ⚠️ SQL 里的 `>= 2` 是 RELAX_LEVEL_CATEGORY_SPREAD 的当前值, 不是写死的门槛:
    阶梯调档时以常量为准, 先把这行 SQL 改掉再跑。
    """
    filters = [
        DecisionLog.created_at >= since,
        # PRD 行动项 12x —— 空壳行过滤。**必须写在 candidate_count 这一列上**:
        # candidate_count 是 NOT NULL DEFAULT 0, R-07 上线之前那 190 行存量数据该列
        # 全是 0。P10 会被直接拉到 0、"< 8 占比"拉到 100%, 判据上线首日恒失败,
        # 而失败原因跟产品毫无关系(是数据模型演进留下的空壳行)。
        #
        # 🔴 不能写成 COALESCE(band_size, candidate_count) > 0:
        #    那会把 band_size = 0(真·抽签带空了)的行一并滤掉, 而那正是 J7' 唯一要抓的
        #    缺陷信号。两句话必须分开读:
        #      candidate_count > 0   → 这一轮**有没有量过**池子 (排除空壳行)
        #      池子读数              → 量出来是**多少** (现在只读 candidate_count)
        #    合成一个过滤条件 = 把"量出来是 0"的缺陷信号当成空壳行扔掉, 判据永远假绿。
        #
        # ⚠️ 与 since 是**叠加**不是替代: since 是入参, 传早了照样中招, 时间窗挡不住
        #    "参数传错"这一类 —— 所以这一条不能省。
        DecisionLog.candidate_count > 0,
    ]
    if until is not None:
        filters.append(DecisionLog.created_at < until)

    total_expr = func.count(DecisionLog.id)
    deep_expr = func.sum(case((DecisionLog.relaxed_level >= DEEP_RELAXATION_LEVEL, 1), else_=0))
    # J3b 观测项: 任一放宽。不设目标, 只用来和旧口径做趋势对照
    any_expr = func.sum(case((DecisionLog.relaxed_level >= 1, 1), else_=0))

    overall = await db.execute(select(total_expr, deep_expr, any_expr).where(*filters))
    total, deep, any_relaxed = _counts(overall.one())

    # J6'/J7' 的池子读数: 逐行取值后在 Python 里算 P10, 所以这里多取一次
    # (meal_slot, candidate_count)。只有 candidate_count, 不再 COALESCE 抽签带 —— 12y。
    pairs = (
        await db.execute(select(DecisionLog.meal_slot, DecisionLog.candidate_count).where(*filters))
    ).all()
    values = [int(row[1]) for row in pairs]
    by_slot_values: Dict[str, List[int]] = {}
    for slot, value in pairs:
        by_slot_values.setdefault(slot, []).append(int(value))

    by_slot_rows = (
        await db.execute(
            select(
                DecisionLog.meal_slot,
                func.count(DecisionLog.id),
                func.sum(case((DecisionLog.relaxed_level >= DEEP_RELAXATION_LEVEL, 1), else_=0)),
                # 中位数量级的辅助读数: 平均放宽级别比 "有没有放宽" 更早反映池子在被抽干
                func.avg(DecisionLog.relaxed_level),
            )
            .where(*filters)
            .group_by(DecisionLog.meal_slot)
        )
    ).all()

    return {
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        "decisions": total,
        "deep_relaxed": deep,
        "deep_relaxed_rate": _rate(deep, total),
        "any_relaxed": any_relaxed,
        "any_relaxed_rate": _rate(any_relaxed, total),
        # ---- J6' / J7': 全部只读 candidate_count ----
        **_pool_stats(values),
        # 阈值一并交出去, 免得报表侧自己写死 8
        "pool_min": POOL_MIN_THRESHOLD,
        # 样本量闸门: 数字照样给, 但 verdict 明确说能不能下结论。
        # 不这么做的话, 夜宵档 3 次决策里 0 次深度放宽 = 0.0%, 报表上比全时段还好看,
        # 而它其实什么都不代表。
        "min_sample_size": MIN_SAMPLE_SIZE,
        "verdict": _verdict(total),
        "by_meal_slot": [
            {
                "meal_slot": row[0],
                "decisions": int(row[1]),
                "deep_relaxed": int(row[2] or 0),
                "deep_relaxed_rate": _rate(int(row[2] or 0), int(row[1])),
                "avg_relaxed_level": round(float(row[3] or 0), 3),
                **_pool_stats(by_slot_values.get(row[0], [])),
                "verdict": _verdict(int(row[1])),
            }
            for row in by_slot_rows
        ],
    }


async def band_width_p10(
    db: AsyncSession, since: datetime, until: datetime | None = None
) -> Dict[str, Any]:
    """抽签带宽度 P10 —— 「池子够、但带塌了」这一类失败的**唯一**读数

    🔴 **只记录、不判定**: 阈值等数析实测之后再定。返回 `verdict = RECORD_ONLY`
    (它不是 "ok"), 报表侧的规矩是 `verdict != "ok"` 就显示"暂不判定"(PRD §5.6),
    所以在阈值落地之前这里的数字只能观测、不能拿去过/不过。
    不许先拍一个阈值再拿它去判 —— 那和"用恒真读数下结论"是同一类错误。

    为什么必须独立于 J6'/J7' (12y): candidate_count 回答"会不会筛不出菜",
    natural_band_size 回答"用户实际在几道里抽"。两者曾经被
    `COALESCE(band_size, candidate_count)` 糊成一列, 于是「池子够、带塌了」隐身 ——
    而那正是这一整版在修的失败(meal_slots 塌到 9 道、早餐 14 道、R-09 归一化后
    60 → 3)。两种失败 = 两条判据。

    为什么用 natural_band_size 而不是 band_size: band_size 有 padding 地板
    (`_random_band` 不足 random_min_choices=3 会按分数补齐), `band_size >= 3` **恒真**。

    口径: `natural_band_size IS NOT NULL` —— NULL = 当时没测(老行), 不能当 0;
    **0 是真的"带空了", 必须留下**, 它是这里唯一要抓的缺陷信号。
    空壳行(`candidate_count = 0`)同样排除, 与 `exhaustion_rate()` 同口径。
    """
    filters = [
        DecisionLog.created_at >= since,
        DecisionLog.candidate_count > 0,
        DecisionLog.natural_band_size.isnot(None),
    ]
    if until is not None:
        filters.append(DecisionLog.created_at < until)

    pairs = (
        await db.execute(
            select(DecisionLog.meal_slot, DecisionLog.natural_band_size).where(*filters)
        )
    ).all()
    values = [int(row[1]) for row in pairs]
    grouped: Dict[str, List[int]] = {}
    for slot, value in pairs:
        grouped.setdefault(slot, []).append(int(value))

    return {
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        # 参与统计的行数: 老行(没测过真带)不算进来, 所以它可能小于 decisions
        "measured": len(values),
        "p10_natural_band_size": _percentile(values, 0.10),
        "min_natural_band_size": min(values) if values else None,
        # ---- 只记录不判定 ----
        "threshold": None,
        "verdict": RECORD_ONLY,
        "note": (
            "阈值待数析实测; 落地时在这里引用常量(参考 DEEP_RELAXATION_LEVEL 那段理由), "
            "不要写死数字, 也不要复用 POOL_MIN"
        ),
        "by_meal_slot": [
            {
                "meal_slot": slot,
                "measured": len(vals),
                "p10_natural_band_size": _percentile(vals, 0.10),
                "min_natural_band_size": min(vals),
                "verdict": RECORD_ONLY,
            }
            for slot, vals in sorted(grouped.items())
        ],
    }


def _verdict(sample: int) -> str:
    """这一格能不能下结论 —— 样本不够就是不够, 别拿小数当结论"""
    if sample <= 0:
        return "no_data"
    if sample < MIN_SAMPLE_SIZE:
        return "insufficient_sample"
    return "ok"


def _pool_stats(values: List[int]) -> Dict[str, Any]:
    """J6' / J7' 的四个读数 —— **全部只基于 candidate_count** (12y)

    不做 COALESCE: 抽签带(band_size / natural_band_size)是另一种失败, 归
    `band_width_p10()`。把它们并进来的话, "池子够、带塌了"会隐身。
    """
    if not values:
        # 空样本一律 None / 0.0 而不是 0: 0 会被读成"池子空了", 那是缺陷信号
        return {
            "p10_candidate_count": None,
            "min_candidate_count": None,
            "below_pool_min": 0,
            "below_pool_min_rate": 0.0,
        }
    below = sum(1 for v in values if v < POOL_MIN_THRESHOLD)
    return {
        # J6': 夜宵档 P10 >= POOL_MIN
        "p10_candidate_count": _percentile(values, 0.10),
        # 辅助读数: 最枯竭的那一格。比 P10 严, 只用来定位, 不拿来判
        "min_candidate_count": min(values),
        # J7': 分档占比 <= 5%
        "below_pool_min": below,
        "below_pool_min_rate": _rate(below, len(values)),
    }


def _percentile(values: List[int], fraction: float) -> int | None:
    """nearest-rank 百分位: 排序后取第 ceil(fraction * n) 小的那个值

    为什么在 Python 里算而不是写成 SQL: MySQL 没有可移植的 percentile 聚合
    (各家方言 PERCENTILE_CONT / percentile_cont() WITHIN GROUP 写法都不一样),
    写进 SQL 就把本模块绑死在一种方言上, 而换方言时它不会报错、只会算错。
    nearest-rank 是 PRD §5.6 里 J6' 用的定义(第 10 百分位 = 第 ceil(0.1n) 小的值),
    **不是线性插值** —— 与数析那边的口径一致, 换算法要双方一起换。
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _counts(row: Any) -> Tuple[int, int, int]:
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _loads(raw: str | None) -> Dict[str, Any] | None:
    """properties 是自由格式的 JSON 字符串, 坏数据不该让整个会话回放失败"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None
