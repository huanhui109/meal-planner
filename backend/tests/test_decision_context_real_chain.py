"""决策上下文落库: 走真实调用链 (decide → _persist → decision_log)

为什么单独一个文件:
    构造 `DecisionLog(...)` 断言"这一列存在"再全也证明不了**生产链路真的写了它** ——
    `_persist()` 少传一个 kwarg, 列有默认值 0 / NULL, 构造式测试照样全绿。
    `/api/decide` 曾经全量 TypeError 而 831 个用例全绿, 就是同一个盲区:
    所有测试都直接构造 `DecisionService`, 没人真跑一遍链路。

    所以这里真跑一次 `decide()`, 再把**落库的那一行读回来**断言。
    判据一律是"值对不对", 不是"字段在不在":
        hasattr(DecisionLog, "reroll_index")        —— 恒真, 不许这么写
        row.reroll_index == 2                       —— 少传 kwarg 就红

为什么自己建 SQLite 而不是用 conftest 的 db_session:
    集成测试统一跑 MySQL (见 conftest 的说明), 但那个 fixture 在没有
    TEST_DATABASE_URL 的环境里是 **skip** 的 —— 一条永远不执行的断言等于没有断言。
    这三条断言只涉及标量与 JSON 列的"写进去 / 读回来", 不碰 conftest 点名的那几处
    MySQL 方言差异 (外键级联 / JSON 内查询 / 前缀索引), SQLite 不会给假绿。

唯一的外接依赖是天气: `WeatherService.get()` 会打外部接口, 这里替换成固定返回值。
它不是被测链路的一环 (被测的是"上下文有没有落库"), 让它联网只会让用例变成 flaky。
"""
from __future__ import annotations

from datetime import datetime

import pytest_asyncio
from app.config import get_settings
from app.models.base import Base
from app.models.decision import DecisionLog
from app.services.decision_service import DecisionService
from app.services.weather_service import WeatherContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.factories import make_user

SESSION_ID = "  sess-real-chain-001  "  # 前后留白: 顺带验落库前做过清洗
CLEANED_SESSION_ID = "sess-real-chain-001"


class _FixedWeather:
    """固定天气 —— 只为了不让用例联网"""

    def __init__(self, condition: str = "clear"):
        self._condition = condition

    async def get(self):
        return WeatherContext(condition=self._condition)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _decide_once(db: AsyncSession, **kwargs) -> DecisionLog:
    """真跑一次 decide(), 返回落库的那一行"""
    user = await make_user(db, open_id=f"ou_real_chain_{kwargs.get('reroll_index', 0)}")
    await db.commit()

    svc = DecisionService(db)
    svc.weather_service = _FixedWeather(kwargs.pop("condition", "clear"))
    await svc.decide(user_id=user.id, **kwargs)
    await db.commit()

    row = (
        await db.execute(
            select(DecisionLog).where(DecisionLog.user_id == user.id).order_by(DecisionLog.id.desc())
        )
    ).scalars().first()
    assert row is not None, "decide() 没有落库 —— 后面的断言就都失去意义了"
    return row


class TestContextReachesTheRow:
    """session_id / reroll_index / filters_snapshot: 列存在 ≠ 写了值"""

    async def test_session_id_is_persisted_and_cleaned(self, db):
        """会话 ID 要落到真列上, 而且是清洗过的那个值 —— 不是原样带空白存进去"""
        row = await _decide_once(db, session_id=SESSION_ID)
        assert row.session_id == CLEANED_SESSION_ID

    async def test_reroll_index_is_persisted(self, db):
        """「用户换几次才肯接受」这条曲线全靠这一列 —— 恒为 0 就等于没埋"""
        first = await _decide_once(db, session_id="sess-a", reroll_index=0)
        assert first.reroll_index == 0

        rerolled = await _decide_once(db, session_id="sess-b", reroll_index=2)
        assert rerolled.reroll_index == 2

    async def test_filters_snapshot_is_persisted_with_content(self, db):
        """快照要能回答"当时是按什么卡的我" —— 断言**值**, 不是"字段不是 NULL"

        两种恒真写法都不许出现在这里:
            hasattr(DecisionLog, "filters_snapshot")   —— 列在就够了, 恒真
            is not None                                —— 空 dict 也非 NULL
            snap["avoid_count"] >= 0                   —— 计数天然非负, 还是恒真
        所以这里把落库的那一行与"这批输入该算出来的期望值"**整体比对**: 少传、传错、
        写错键名, 三种情况都会红。

        ⚠️ 还要配上下一条才会真的拴住: 只对一个输入比对期望值, 挡不住有人把 filters
        写死成一个常量 dict —— 那种写法过得了这一条, 过不了下一条。
        """
        row = await _decide_once(
            db, session_id="sess-c", reroll_index=1, meal_slot="dinner", exclude=["番茄炒蛋"]
        )
        snap = row.filters_snapshot
        assert isinstance(snap, dict) and snap, f"快照是空的: {snap!r}"
        assert snap == {
            "meal_slot": "dinner",
            "cook_cap": 60,                 # 没有 household 档案时的默认耗时上限
            "late_night_max_minutes": None,  # 只在夜宵档写, 晚饭必须是 None
            "avoid_count": 0,                # make_user 不建偏好/过敏档案
            "allergen_count": 0,
            "excluded_count": 1,             # 传入的排除项: 少传 kwargs 就会掉成 0
            "has_intent": False,             # 没传 utterance, 不该有口语诉求
            "meal_budget": None,             # 没设过预算
            "relaxed_level": 0,              # 本地池兜底, 晚饭不需要放宽
            # 测试库里没有 recipe 行 → 候选 0 道 < 20, 走本地池补齐。
            # 这个 key 是 T01 的观测标记: 补齐那批菜零过滤(含忌口), 但凡它 true,
            # 快照里那些 avoid/allergen 计数就只描述了一半的候选。
            "pool_topped_up": True,
        }

    async def test_filters_snapshot_tracks_the_actual_arguments(self, db):
        """换一组输入, 快照里的值必须跟着变 —— 这条才抓得住"写死成常量 dict"

        与上一条是一对: 上一条证明"这一行等于期望值", 这条证明"两行之间随输入变化"。
        缺了它, 把 `_filters_snapshot(...)` 换成一个写死的常量 dict 照样全绿, 而这一列的用途
        ("那一刻到底按什么卡的我") 会当场作废。
        """
        wee_hours = datetime.now().replace(hour=23, minute=30)
        dinner_row = await _decide_once(
            db, session_id="sess-e", reroll_index=3, meal_slot="dinner",
            exclude=["番茄炒蛋"], now=wee_hours,
        )
        late_row = await _decide_once(
            db, session_id="sess-f", reroll_index=4, meal_slot="late_night",
            exclude=["番茄炒蛋", "红烧肉"], now=wee_hours,
        )
        dinner_snap, late_snap = dinner_row.filters_snapshot, late_row.filters_snapshot

        # 同一个字段随入参变化: 排除项个数
        assert dinner_snap["excluded_count"] == 1
        assert late_snap["excluded_count"] == 2
        # 餐次相关的字段随餐次变化 —— 不是从某个行上下文里漏过来的旧值
        assert dinner_snap["meal_slot"] == "dinner"
        assert late_snap["meal_slot"] == "late_night"
        late_cap = get_settings().decide.late_night_max_minutes
        assert dinner_snap["late_night_max_minutes"] is None
        assert late_snap["late_night_max_minutes"] == late_cap

    async def test_band_sizes_also_come_from_the_real_chain(self, db):
        """顺带: 两个带大小同样只信真链路 —— 构造式断言抓不到 _persist 漏传"""
        row = await _decide_once(db, session_id="sess-d")
        assert row.band_size is not None and row.band_size >= 1
        assert row.natural_band_size is not None and row.natural_band_size >= 1
        assert row.natural_band_size <= row.band_size


class TestMissingIsDistinguishable:
    """反证: 上面那些断言真的能区分"写了"和"没写"

    少传 kwargs 时这些列是 None / 0 —— 与上面对照, 说明判据不是恒真的。
    没有这一组, 上面对"值"的断言随时可能被人改成恒真而没人发现。
    """

    async def test_persist_without_context_leaves_the_columns_empty(self, db):
        svc = DecisionService(db)
        await svc._persist(  # noqa: SLF001
            user_id=1,
            picked=__import__("app.services.decision_service", fromlist=["Candidate"]).Candidate(
                id=1, name="番茄炒蛋", cuisine="家常", category="荤菜", main="鸡蛋",
                minutes=12, calories=220, difficulty=1, spice=0, light=False, cover="下饭",
                tags=[], flavors=[], ingredients=["鸡蛋"], steps=["a"], from_pool=True,
            ),
            result={"reason": "今天这个，不亏。"},
            slot="dinner",
            weather=WeatherContext(),
            today=datetime.now().date(),
        )
        await db.commit()
        row = (await db.execute(select(DecisionLog))).scalars().first()
        assert row.session_id is None
        assert row.reroll_index == 0
        assert row.filters_snapshot is None
        assert row.band_size is None
        assert row.natural_band_size is None
