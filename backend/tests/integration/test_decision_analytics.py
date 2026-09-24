"""V1.2.0 R-06 / R-07 / R-16 埋点基建集成测试

这几条测试是为了回答同一个问题: **这次改版能不能归因**。
- 会话能不能串起来 (test_events_batch... / test_session_timeline...)
- J3 能不能不靠解析 JSON 算出来 (test_exhaustion_rate...)
- 灰度版本能不能落到真列上，且"不知道"不等于"在 v1.2 组" (test_layout_version...)

真 MySQL 而不是 SQLite: 这两张表上带着外键、JSON 列、前缀索引,
SQLite 会给假绿。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.decision import DecisionLog, DecisionSource, MealSlot
from app.models.event import Event
from app.services.decision_metrics import (
    DEEP_RELAXATION_LEVEL,
    MIN_SAMPLE_SIZE,
    RECORD_ONLY,
    band_width_p10,
    exhaustion_rate,
    session_timeline,
)
from app.services.decision_service import POOL_MIN, RELAX_LEVEL_CATEGORY_SPREAD
from sqlalchemy import select

from tests.factories import make_user

# 两个互不相同的会话 ID —— "会话不串号"这件事本身要有反例
_SESSION_A = str(uuid.uuid4())
_SESSION_B = str(uuid.uuid4())


async def _report(api_client, session_id: str, events: list[dict]) -> dict:
    resp = await api_client.post("/api/events", json={"events": events})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_events_batch_persists_session_and_decision(api_client, db_session):
    """session_id/decision_id 必须落到真列上, 不是落进 props JSON

    这里只喂 4 条: 验证的是"列有没有接住", 不是"11 个事件名有没有都覆盖" ——
    事件名的完整清单在 test_session_timeline_returns_full_sequence 里。
    """
    user = await make_user(db_session, open_id="ou_events_self")
    await db_session.commit()

    decision = DecisionLog(
        user_id=user.id,
        dish_name="番茄炒蛋",
        decision_date=datetime.now().date(),
        meal_slot=MealSlot.DINNER,
        source=DecisionSource.LOCAL,
        session_id=_SESSION_A,
        relaxed=True,
        relaxed_level=3,
        candidate_count=6,
        reroll_index=2,
        filters_snapshot={"max_minutes": 30, "avoid": ["香菜"]},
    )
    db_session.add(decision)
    await db_session.commit()

    ack = await _report(
        api_client,
        _SESSION_A,
        [
            # 决策之前的事件: 没有 decision_id, 这是最常见的情形
            {
                "event_name": "home_view",
                "ts": 1_770_000_000_000,
                "properties": {"layout_version": "v1.2"},
                "session_id": _SESSION_A,
            },
            {
                # home_filter_tap 已随 J6/J7 一并作废(PRD v1.6, 事件清单 12→11),
                # 这里换成仍在清单里的事件, 免得后人照着测试文件去找一个已删的事件
                "event_name": "decide_roll",
                "ts": 1_770_000_100_000,
                "properties": {"source": "button"},
                "session_id": _SESSION_A,
            },
            # 决策之后: decision_id 有值, 用来join回 decision_log 看放宽级别
            {
                "event_name": "decide_result_shown",
                "ts": 1_770_000_200_000,
                "properties": {"relaxed": True, "relaxed_level": 3, "candidate_count": 6},
                "session_id": _SESSION_A,
                "decision_id": decision.id,
            },
            {
                "event_name": "decide_accept",
                "ts": 1_770_000_300_000,
                "properties": {"result_age_ms": 4200},
                "session_id": _SESSION_A,
                "decision_id": decision.id,
            },
            # 同批里另一个会话, 验证不会串 session
            {
                "event_name": "home_view",
                "ts": 1_770_000_400_000,
                "session_id": _SESSION_B,
            },
        ],
    )
    assert ack["accepted"] == 5, ack

    rows = (await db_session.execute(_events_of(_SESSION_A))).scalars().all()
    assert len(rows) == 4
    assert [r.event_name for r in rows] == [
        "home_view",
        "decide_roll",
        "decide_result_shown",
        "decide_accept",
    ]
    # decision_id 只有结果之后的事件才有
    assert [r.decision_id for r in rows] == [None, None, decision.id, decision.id]
    # 允许 NULL: "决策之前"的事件是本版本绝大多数事件的真实状态
    other = (await db_session.execute(_events_of(_SESSION_B))).scalars().all()
    assert len(other) == 1
    assert other[0].decision_id is None


async def test_session_id_falls_back_to_properties(api_client, db_session):
    """双端 track 现在把 session_id 塞在 properties 里, 后端不能把它写成 NULL

    这是接不住就没人会发现的那类 BUG: J1 闭环率的分母是会话数, 列全空 = 这次埋点白做,
    但接口照样返回 200、事件照样落库。等前端改造完成、改成顶层传之后, 这段兜底可以删。
    """
    await make_user(db_session, open_id="ou_events_legacy")
    await db_session.commit()

    ack = await _report(
        api_client,
        _SESSION_B,
        [
            {
                "event_name": "decide_roll",
                "ts": 1_770_000_900_000,
                "properties": {"session_id": _SESSION_B, "result_count": 6},
            },
            # 两处都给值时顶层优先: 顶层是明确意图, properties 里的是历史包袱
            {
                "event_name": "home_view",
                "ts": 1_770_001_000_000,
                "session_id": _SESSION_A,
                "properties": {"session_id": _SESSION_B},
            },
        ],
    )
    assert ack["accepted"] == 2, ack

    rows = (await db_session.execute(_events_of(_SESSION_B))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_name == "decide_roll"
    top_level_rows = (await db_session.execute(_events_of(_SESSION_A))).scalars().all()
    assert [r.event_name for r in top_level_rows] == ["home_view"]


async def test_session_timeline_returns_full_sequence(db_session):
    """按 session_id 能还原一次「打开首页 → 定下来」的完整过程

    客户端 ts 是**故意写反的**: 如果有人将来改用 ts 排序, 这条测试会立刻红 ——
    会话内部的先后顺序错了, 序列分析就没有意义。
    """
    user = await make_user(db_session, open_id="ou_events_seq")
    base = datetime(2026, 9, 23, 18, 0, 0)
    # 全部取自 PRD v1.6 定稿的 11 个事件清单 (home_filter_tap 已作废删除)
    names_in_order = [
        "home_view",
        "decide_roll",
        "decide_result_shown",
        "decide_view_steps",
        "decide_accept",
    ]
    for index, name in enumerate(names_in_order):
        db_session.add(
            Event(
                user_id=user.id,
                event_name=name,
                # ts 与真实顺序完全相反
                ts=1_770_000_500_000 - index * 1000,
                received_at=base + timedelta(seconds=index),
                session_id=_SESSION_A,
                properties='{"step": 2}' if name == "decide_view_steps" else None,
            )
        )
    await db_session.commit()

    timeline = await session_timeline(db_session, _SESSION_A)
    assert [r["event_name"] for r in timeline] == names_in_order
    # 收到时间是升序 —— 它就是 v1.2.0 全部指标的时间口径
    assert [r["received_at"] for r in timeline] == sorted(r["received_at"] for r in timeline)
    assert timeline[3]["properties"] == {"step": 2}
    # 客户端时间戳必须原样带出来, 但它的顺序是乱的: 这条断言写的是"它不可信"
    assert [r["client_ts"] for r in timeline] == sorted(
        (r["client_ts"] for r in timeline), reverse=True
    )


async def test_layout_version_lands_in_real_column(api_client, db_session):
    """R-16: 灰度版本要落到真列上, 且"取不到"必须是 NULL 而不是 'v1.2'

    后端替前端兜底是这个版本最容易悄无声息犯的错: 一旦把"不知道用户在哪个组"
    写成 'v1.2', 这批用户就被算进 v1.2 样本, 灰度结论直接失效。
    """
    await make_user(db_session, open_id="ou_events_layout")
    await db_session.commit()

    ack = await _report(
        api_client,
        _SESSION_A,
        [
            # 顶层下发 —— 这是双端改造完之后的形态
            {
                "event_name": "home_view",
                "ts": 1_770_002_000_000,
                "layout_version": "v1.1",
                "session_id": _SESSION_A,
            },
            # 只在 properties 里 —— 现在的过渡形态, 回落必须接住
            {
                "event_name": "decide_roll",
                "ts": 1_770_002_100_000,
                "properties": {"layout_version": "v1.2"},
                "session_id": _SESSION_A,
            },
            # 一处都没有 —— 必须是 NULL, 绝不能被填成某个默认组
            {"event_name": "decide_accept", "ts": 1_770_002_200_000, "session_id": _SESSION_A},
        ],
    )
    assert ack["accepted"] == 3, ack

    rows = (await db_session.execute(_events_of(_SESSION_A))).scalars().all()
    versions = {r.event_name: r.layout_version for r in rows}
    assert versions == {
        "home_view": "v1.1",
        "decide_roll": "v1.2",
        "decide_accept": None,  # ← 不知道就不知道, 不许猜成一个组
    }


async def test_decision_id_zero_is_stored_as_null(api_client, db_session):
    """离线兜底结果的 decision_id=0 必须落成 NULL, 不能拿去撞外键

    离线决策在 `decision_log` 里**没有行**(它是"永远有答案"的兜底路径), 前端用 0
    表示"没有"(dev-h5-home 的 `toResult()`)。而 0 不是合法的 `decision_log.id`:
    写库会在 **commit** 时被外键拒掉(1452) —— commit 在循环**外面**, 没被 per-event
    的 try 接住, 于是整批事件一起 500。埋点绝不能因为一个占位值打断主流程。

    NULL 在这里也是**符合事实**的: 这次确实没有对应的决策流水行。
    """
    await make_user(db_session, open_id="ou_events_offline_id")
    await db_session.commit()

    ack = await _report(
        api_client,
        _SESSION_B,
        [
            {
                "event_name": "decide_result_shown",
                "ts": 1_770_003_000_000,
                "session_id": _SESSION_B,
                "decision_id": 0,
            },
        ],
    )
    assert ack["accepted"] == 1, ack
    rows = (await db_session.execute(_events_of(_SESSION_B))).scalars().all()
    assert [r.decision_id for r in rows] == [None]


async def test_exhaustion_rate_reads_real_columns(db_session):
    """J3 必须能从真列算出来 —— payload 里的 relaxed 是假的也不能影响结果"""
    user = await make_user(db_session, open_id="ou_events_j3")
    now = datetime.now()
    # payload 一律写 "relaxed": true —— 若有人退回 LIKE 扫 JSON, 率会变成 100%,
    # 而正确答案是 2/5 (5 档口径下 >= RELAX_LEVEL_CATEGORY_SPREAD 的只有 2 条)
    lying_payload = '{"relaxed": true, "advice": "故意写死, 用来证明不再读这里"}'

    # (餐次, 放宽级别, candidate_count, band_size, natural_band_size)
    # —— 两列都为 None 模拟老决策行
    combos = [
        (MealSlot.DINNER, 0, 180, 116, 116),  # 晚饭: 池子 180 但只在 116 道里抽
        (MealSlot.DINNER, 2, 12, 5, 5),
        (MealSlot.DINNER, 0, 2, None, None),  # ← 老行没测 band, 必须回落到 2 而不是 0
        # ← padding 陷阱: 真带只剩 1 道, 但 band_size 被补齐顶到下限 3
        (MealSlot.LATE_NIGHT, 4, 3, 3, 1),
        (MealSlot.LATE_NIGHT, 1, 9, 4, 2),
    ]
    for slot, level, candidates, band, natural in combos:
        db_session.add(
            DecisionLog(
                user_id=user.id,
                dish_name=f"{slot}-{level}-{candidates}",
                decision_date=now.date(),
                meal_slot=slot,
                source=DecisionSource.LOCAL,
                session_id=_SESSION_A,
                relaxed=level > 0,
                relaxed_level=level,
                candidate_count=candidates,
                band_size=band,
                natural_band_size=natural,
                reroll_index=1,
                filters_snapshot={"slot": slot},
                payload=lying_payload,
            )
        )
    await db_session.commit()

    result = await exhaustion_rate(db_session, since=now - timedelta(hours=1))
    assert result["decisions"] == 5
    # 深度放宽 = level >= 2 (category 打散起): level 2 与 level 4 两条
    assert result["deep_relaxed"] == 2
    assert result["deep_relaxed_rate"] == 0.4
    # J3b 任一放宽: level 2/4/1 三条
    assert result["any_relaxed"] == 3

    # ---- J6' / J7': 池子读数**只读 candidate_count** (12y), 不再 COALESCE 抽签带 ----
    # candidate_count 依次是 180 / 12 / 2 / 3 / 9
    assert result["min_candidate_count"] == 2
    # nearest-rank P10: 排序 [2,3,9,12,180], 第 ceil(0.1*5)=1 小 → 2
    assert result["p10_candidate_count"] == 2
    # J7' 分子: 低于 POOL_MIN(8) 的是 2 和 3 两条
    assert result["below_pool_min"] == 2
    assert result["below_pool_min_rate"] == 0.4
    assert result["pool_min"] == POOL_MIN

    slots = {row["meal_slot"]: row for row in result["by_meal_slot"]}
    # 夜宵 20% 上限是单独一条线, 不能被全时段平均掉
    assert slots[MealSlot.DINNER]["decisions"] == 3
    assert slots[MealSlot.DINNER]["deep_relaxed"] == 1
    assert slots[MealSlot.LATE_NIGHT]["decisions"] == 2
    assert slots[MealSlot.LATE_NIGHT]["deep_relaxed"] == 1
    assert slots[MealSlot.LATE_NIGHT]["deep_relaxed_rate"] == 0.5
    # 分档的池子读数同样只读 candidate_count: 晚饭 [180,12,2]、夜宵 [3,9]
    assert slots[MealSlot.DINNER]["min_candidate_count"] == 2
    assert slots[MealSlot.DINNER]["p10_candidate_count"] == 2
    assert slots[MealSlot.LATE_NIGHT]["min_candidate_count"] == 3
    assert slots[MealSlot.LATE_NIGHT]["p10_candidate_count"] == 3
    assert slots[MealSlot.LATE_NIGHT]["below_pool_min"] == 1

    # 抽签带宽度是**另一条**判据, 不在本函数里 —— 12y
    assert "min_natural_band_size" not in result
    assert "min_pool_size" not in result

    # since 之前的历史行不算进来 (这是 R-07 ④ 的要求: 190 行压测数据不参与指标)
    old = await exhaustion_rate(db_session, since=now + timedelta(hours=1))
    assert old["decisions"] == 0
    assert old["deep_relaxed_rate"] == 0.0
    # 空样本给 None / 0.0, 不是 0 —— 0 会被读成"池子空了", 那是缺陷信号
    assert old["min_candidate_count"] is None
    assert old["p10_candidate_count"] is None
    assert old["below_pool_min"] == 0


async def test_empty_shell_rows_are_excluded_but_zero_band_is_kept(db_session):
    """12x: candidate_count=0 的空壳行要排除, band_size=0 的缺陷行必须留下

    两个 0 必须分得开:
      candidate_count = 0  → "这一轮没量过池子"。R-07 上线前那 190 行全是它,
                             混进分母会把 P10 拉到 0、"< 8 占比"拉到 100%,
                             判据上线首日恒失败, 而失败原因跟产品毫无关系。
      band_size = 0        → "量出来了, 是 0 —— 抽签带空了"。这是 J7' 唯一要抓的
                             缺陷信号, 滤掉它判据就永远假绿。

    过滤条件一旦写成 COALESCE(band_size, candidate_count) > 0, 这两类会被一起滤掉;
    写对位置(只滤 candidate_count)之后, 前者出局、后者留下。

    ⚠️ 12y 之后 band_size=0 这个缺陷信号**不在** exhaustion_rate() 里看了 —— 池子读数
    只保留 candidate_count, 抽签带宽度归 `band_width_p10()`, 那里同样必须看得见 0。
    """
    user = await make_user(db_session, open_id="ou_events_shell")
    now = datetime.now()

    def _row(dish: str, candidates: int, band: int | None, natural: int | None) -> DecisionLog:
        return DecisionLog(
            user_id=user.id,
            dish_name=dish,
            decision_date=now.date(),
            meal_slot=MealSlot.DINNER,
            source=DecisionSource.LOCAL,
            relaxed_level=0,
            candidate_count=candidates,
            band_size=band,
            natural_band_size=natural,
        )

    db_session.add(_row("空壳行-没量过", 0, None, None))
    db_session.add(_row("真抽签带空了-缺陷信号", 6, 0, 0))
    db_session.add(_row("正常", 20, 8, 8))
    await db_session.commit()

    result = await exhaustion_rate(db_session, since=now - timedelta(hours=1))
    # 空壳行不进分母
    assert result["decisions"] == 2
    # 池子读数只剩 candidate_count: [6, 20] —— 6 那条仍在(它量过池子, 只是带空了)
    assert result["min_candidate_count"] == 6
    assert result["below_pool_min"] == 1  # 6 < POOL_MIN(8)

    # 抽签带空了这件事去 band_width_p10() 看, 而且必须看得见 0
    band = await band_width_p10(db_session, since=now - timedelta(hours=1))
    assert band["measured"] == 2  # natural_band_size: 0 与 8
    assert band["min_natural_band_size"] == 0
    assert band["p10_natural_band_size"] == 0


async def test_band_width_p10_records_without_judging(db_session):
    """12y: 抽签带宽度独立成一条判据, 且**阈值落地前只记录不判定**

    这批数据是 COALESCE 会让它彻底隐身的那一类失败: 池子都不小(candidate_count
    全部 >= 30), 但抽签带已经塌到 1-3 道。糊成一列时 J6'/J7' 报"健康"。

    另一半钉的是"不许先拍一个阈值": 返回的 threshold 必须是 None、verdict 必须
    **不等于 ok** —— 报表侧看到 != "ok" 就会显示"暂不判定"(PRD §5.6)。
    如果这里自己编一个阈值, 就没人会再去问数析真实分布是什么。
    """
    user = await make_user(db_session, open_id="ou_events_band")
    now = datetime.now()
    for slot, candidates, natural in [
        (MealSlot.DINNER, 60, 3),
        (MealSlot.DINNER, 40, 2),
        (MealSlot.LATE_NIGHT, 30, 1),
    ]:
        db_session.add(
            DecisionLog(
                user_id=user.id,
                dish_name=f"{slot}-band-{natural}",
                decision_date=now.date(),
                meal_slot=slot,
                source=DecisionSource.LOCAL,
                relaxed_level=0,
                candidate_count=candidates,
                # padding 把 band_size 顶到下限 3, 真带是 natural —— 两个都要写
                band_size=max(natural, 3),
                natural_band_size=natural,
            )
        )
    await db_session.commit()

    band = await band_width_p10(db_session, since=now - timedelta(hours=1))
    assert band["measured"] == 3
    # nearest-rank P10: 排序 [1,2,3], 第 ceil(0.1*3)=1 小 → 1
    assert band["p10_natural_band_size"] == 1
    assert band["min_natural_band_size"] == 1
    # 🔴 只记录不判定
    assert band["threshold"] is None
    assert band["verdict"] == RECORD_ONLY
    assert band["verdict"] != "ok"
    by_slot = {row["meal_slot"]: row for row in band["by_meal_slot"]}
    assert by_slot[MealSlot.LATE_NIGHT]["min_natural_band_size"] == 1

    # 同一批数据在 J6'/J7' 里完全健康 —— 这正是两条判据必须分开的理由
    rate = await exhaustion_rate(db_session, since=now - timedelta(hours=1))
    assert rate["min_candidate_count"] == 30
    assert rate["below_pool_min"] == 0


async def test_deep_relaxation_level_follows_the_ladder():
    """J3 门槛必须是"引用常量", 不能再是写死的数字

    这轮它漂过三次(旧 relaxed=true → 6 档的 3 → 5 档的 2), 每次都是"某个数字曾经
    对过"。写死就会在下一次调档时静默指着错误的档位。
    """
    assert DEEP_RELAXATION_LEVEL == RELAX_LEVEL_CATEGORY_SPREAD
    # 5 档口径下它是 2; 断言等于 2 也是为了让人改档时被迫看一眼这条
    assert DEEP_RELAXATION_LEVEL == 2


async def test_small_samples_refuse_to_draw_a_conclusion(db_session):
    """占比类判据没有样本量闸门就会假绿 —— 夜宵档尤其危险

    5 次决策里 0 次深度放宽 = 0.0%, 报表上比全时段的 8% 还好看, 而它什么都不代表
    (n 太小时置信区间比判据阈值还宽)。所以数字照给, 但 verdict 必须说"不能下结论"。
    """
    user = await make_user(db_session, open_id="ou_events_sample")
    now = datetime.now()
    db_session.add(
        DecisionLog(
            user_id=user.id,
            dish_name="夜宵-零放宽",
            decision_date=now.date(),
            meal_slot=MealSlot.LATE_NIGHT,
            source=DecisionSource.LOCAL,
            relaxed_level=0,
            candidate_count=30,
            band_size=12,
        )
    )
    await db_session.commit()

    result = await exhaustion_rate(db_session, since=now - timedelta(hours=1))
    # 数字照给(观测用), 但不许被当成"夜宵 0% 很健康"
    assert result["decisions"] == 1
    assert result["deep_relaxed_rate"] == 0.0
    assert result["verdict"] == "insufficient_sample"
    assert result["min_sample_size"] == MIN_SAMPLE_SIZE
    assert result["by_meal_slot"][0]["verdict"] == "insufficient_sample"

    # 完全没数据更不能算"0% 通过"
    empty = await exhaustion_rate(db_session, since=now + timedelta(hours=1))
    assert empty["verdict"] == "no_data"


def _events_of(session_id: str):
    """按服务端时间排序 —— 与 decision_metrics.session_timeline 保持同一个口径"""
    return (
        select(Event)
        .where(Event.session_id == session_id)
        .order_by(Event.received_at.asc(), Event.id.asc())
    )
