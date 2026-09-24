"""V1.2.0 决策引擎: 夜宵口径 + 5 档放宽阶梯 (R-10) + meal_slots 软惩罚 (R-11)

为什么单独一个文件:
    这三条改的是同一个 `_pick`, 但动机彼此独立, 混在 test_decide_rules.py 里会让
    "哪条承诺归哪条测试负责"变得模糊。每条规则用一个 class, 失败时能直接读到是
    哪一条产品承诺被打穿了。

共同的三条注意点:
    1. 全部纯逻辑, 不连数据库 (DB 相关的放 integration)
    2. 候选池用 _local_candidates() 之类的构造器拼, 不复制业务库里的数据 ——
       数据会变, 断言必须跟着改的话这条测试就白写了
    3. 改动前后最直观的对照写在 docstring 里, 因为这几个数字 (16->45, 0->29)
       是这次改造存在的理由
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from app.config import get_settings
from app.models.decision import MealSlot
from app.services.decision_service import (
    LATE_NIGHT_EXTRA_CATEGORIES,
    MAX_RELAX_LEVEL,
    MEAL_SLOT_MATCH_BONUS,
    MEAL_SLOT_MISMATCH_PENALTY,
    POOL_MIN,
    Candidate,
    DecisionService,
    Profile,
    RecentHistory,
    _clean_session_id,
    _filters_snapshot,
    normalize_dish_name,
)
from app.services.weather_service import WeatherContext

TODAY = date(2026, 9, 23)


def make_candidate(**kwargs) -> Candidate:
    base = dict(
        id=1,
        name="番茄炒蛋",
        cuisine="家常",
        category="荤菜",
        main="鸡蛋",
        minutes=12,
        calories=220,
        difficulty=1,
        spice=0,
        light=False,
        cover="下饭",
        tags=["快手"],
        flavors=["咸鲜"],
        ingredients=["鸡蛋", "番茄", "盐"],
        steps=["a", "b", "c"],
    )
    base.update(kwargs)
    return Candidate(**base)


def make_profile(**kwargs) -> Profile:
    base = dict(cuisines=[], spice_level=2, avoid=[], allergens=[], scene_tags=[], cook_cap=60)
    base.update(kwargs)
    return Profile(**base)


def make_service() -> DecisionService:
    svc = DecisionService.__new__(DecisionService)
    svc.settings = get_settings().decide
    return svc


def passes(dish: Candidate, slot: str, profile: Profile | None = None, **kwargs) -> bool:
    used = profile or make_profile()
    return make_service()._passes(  # noqa: SLF001
        dish,
        used,
        RecentHistory(),
        WeatherContext(),
        set(),
        slot,
        set(),
        cook_cap=kwargs.pop("cook_cap", used.cook_cap),
        **kwargs,
    )


def run_pick(candidates, slot=MealSlot.DINNER, **kwargs) -> tuple:
    """跑一次完整筛选。返回 (选出的菜, 放宽档位, 放宽前池子大小, 实际抽签带大小)"""
    svc = make_service()
    out = svc._pick(  # noqa: SLF001
        candidates=candidates,
        profile=kwargs.pop("profile", make_profile()),
        history=kwargs.pop("history", RecentHistory()),
        weather=WeatherContext(),
        inventory=set(),
        expiring=[],
        slot=slot,
        excluded=set(),
        today=TODAY,
        **kwargs,
    )
    return out.candidate, out.relaxed_level, out.candidate_count, out.band_size


def n_candidates(count: int, category: str = "素菜", **kwargs) -> list[Candidate]:
    """生成 count 道互不重名的候选 —— 菜名与主料都错开, 免得被去重规则误伤"""
    return [
        make_candidate(id=i, name=f"候选菜{i}", main=f"主料{i}", category=category, **kwargs)
        for i in range(count)
    ]


# --------------------------------------------------------------- 夜宵白名单 (任务一)


class TestLateNightWhitelist:
    """改前: is_dish=1 ∩ is_light=1 ∩ <=20min 只有 16 道, 主食/面食/汤羹全为 0
    改后: 夜宵池 16 -> 45; 深夜"想吃碗面"不再是死路
    """

    def test_late_night_allows_staple_and_noodles(self):
        """面食/15min/非轻食 → 放行。这是这次改造要解决的那个"无解"场景"""
        for category in LATE_NIGHT_EXTRA_CATEGORIES:
            assert passes(make_candidate(category=category, light=False, minutes=15),
                          MealSlot.LATE_NIGHT)

    def test_late_night_still_rejects_heavy_dish(self):
        """荤菜/15min/非轻食 → 仍拒绝。白名单不是"深夜什么都能吃"的口子"""
        assert not passes(
            make_candidate(category="荤菜", light=False, minutes=15), MealSlot.LATE_NIGHT
        )

    def test_late_night_still_enforces_minutes(self):
        """面食/60min → 拒绝。白名单菜同样受出餐时间上限约束"""
        assert not passes(
            make_candidate(category="面食", light=False, minutes=60), MealSlot.LATE_NIGHT
        )
        # 边界: 正好卡在上限时放行 (<= 而不是 <, 与旧口径一致)
        assert passes(
            make_candidate(category="面食", light=False, minutes=20), MealSlot.LATE_NIGHT
        )

    def test_staple_not_marked_light(self):
        """is_light 没有被污染 —— 这是本次改造最关键的一条回归

        修这个问题的捷径是把蛋炒饭/挂面标成 is_light=1, 那样代码一行都不用改。
        不能这么做的原因写在 LATE_NIGHT_EXTRA_CATEGORIES 的注释里: is_light 白天还
        要服务"来点清淡的", 把主食标成轻食等于修一个问题制造另一个问题。

        所以这里钉两件事:
          1. 白名单限定在主食/面食, 没有偷偷扩到荤菜/汤羹
          2. 引擎任何地方都不写 is_light —— 进出 Menge发动机的 light 只是 Recipe 的映射
        """
        assert LATE_NIGHT_EXTRA_CATEGORIES == ("主食", "面食")

        svc = make_service()
        dish = make_candidate(category="主食", light=False, minutes=15)
        svc._passes(  # noqa: SLF001
            dish, make_profile(), RecentHistory(), WeatherContext(), set(),
            MealSlot.LATE_NIGHT, set(), cook_cap=60,
        )
        # 过滤不能顺手把 light 打开
        assert dish.light is False

    def test_light_dishes_still_pass_daytime(self):
        """白名单只在深夜生效: 白天(null午餐时段)的过滤规则一个字都没动"""
        noodle = make_candidate(category="面食", light=False, minutes=15)
        for slot in (MealSlot.BREAKFAST, MealSlot.LUNCH, MealSlot.DINNER):
            assert passes(noodle, slot)


# ---------------------------------------------------------------- 5 档阶梯 (R-10)


class TestRelaxLadder:
    """触发条件从 "pool == 0" 改成 "pool < 水位线": 放宽更早, 用户少看一次失败"""

    def test_no_relaxation_when_pool_is_healthy(self):
        """池子够抽签时一档都不松, 并如实上报候选数"""
        _, level, count, band = run_pick(n_candidates(POOL_MIN + 2))
        assert level == 0
        assert count == POOL_MIN + 2

    def test_waterline_relaxes_before_pool_is_empty(self):
        """这是本次的核心改动: 池子没空但不够抽, 也已经放宽了

        旧实现要等 pool==0 才放宽, 于是用户先拿到一次明显不合时宜的结果才触发。
        """
        # cook_cap=10 把 12 道菜砍到 3 道 —— 没空, 但远低于水位线
        candidates = n_candidates(12, minutes=30)
        _, level, count, band = run_pick(candidates, profile=make_profile(cook_cap=10))
        assert level == 1          # 松 cook_cap 就够
        assert count == 0          # 放宽**之前**是空的

    def test_small_library_does_not_over_relax(self):
        """全库不足水位线时不能一路松到最深那档

        总共 5 道菜、没有任何历史约束的时候硬要凑 8 道, 只会一路放宽到动用
        「近 7 天不重复」这条最后防线 —— 池子一点没变大, 用户却吃到了昨天的菜。
        """
        _, level, count, band = run_pick(n_candidates(5))
        assert level == 0
        assert count == 5

    def test_each_level_is_reported(self):
        """每一档都要能被观测到: relaxed_level 是 J3 的分子"""
        # 1) 只有松掉时间上限才够
        assert run_pick(n_candidates(12, minutes=30), profile=make_profile(cook_cap=10))[1] == 1
        # 2) 近 7 天几乎把池子吃光了: 先把历史堆到只剩 4 道
        history = RecentHistory(
            names={normalize_dish_name(f"候选菜{i}") for i in range(8)}
        )
        assert run_pick(n_candidates(12), history=history)[1] == MAX_RELAX_LEVEL

    def test_seven_day_repeat_is_the_last_line(self):
        """「近 7 天不重复」必须在最后一档, 之前的机会都用过才轮到它"""
        history = RecentHistory(names={normalize_dish_name(f"候选菜{i}") for i in range(4)})
        # 选菜是软随机, 单次结果不说明问题; 重复采样到"确实出过窗口内的菜"为止。
        # 走到第 4 档时近 7 天吃过的那批重新回到池子里, 30 次里一次都不出现是不可能的。
        repeats = 0
        for _ in range(30):
            picked, level, _, _band = run_pick(n_candidates(POOL_MIN), history=history)
            assert picked is not None
            assert level == MAX_RELAX_LEVEL
            if normalize_dish_name(picked.name) in history.names:
                repeats += 1
        assert repeats > 0

    def test_allergen_is_never_relaxed(self):
        """忌口/过敏不进阶梯: 5 档里任何一档都不能放行

        逐档核对而不是只试最深那档 —— 中间档是各自独立的配置组合, 哪一档把忌口条件
        漏掉了, 用户就会在那一档上吃到过敏的菜。
        """
        profile = make_profile(avoid=["花生"])
        dishes = [
            make_candidate(id=0, name="宫保鸡丁", category="素菜", main="鸡", minutes=10),
            make_candidate(id=1, name="花生拌黄瓜", category="素菜", main="黄瓜", minutes=10),
        ]
        ladder = make_service()._relax_ladder(make_profile())  # noqa: SLF001
        assert len(ladder) == MAX_RELAX_LEVEL + 1
        for level, relax in enumerate(ladder):
            survivors = [
                c.name
                for c in dishes
                if passes(
                    c, MealSlot.DINNER, profile=profile,
                    cook_cap=relax["cook_cap"], allow_repeat=relax["allow_repeat"],
                )
            ]
            assert survivors == ["宫保鸡丁"], f"第 {level} 档放行了过敏的菜: {survivors}"

    def test_allergen_survives_a_full_pick(self):
        """端到端也过一遍: 走完整条阶梯之后, 被忌口的那道仍然不会出现"""
        profile = make_profile(avoid=["花生"])
        candidates = [
            make_candidate(id=0, name="宫保鸡丁", category="素菜", main="鸡", minutes=10),
            make_candidate(id=1, name="花生拌黄瓜", category="素菜", main="黄瓜", minutes=10),
        ]
        picked, level, count, band = run_pick(candidates, profile=profile)
        assert picked is not None and picked.name == "宫保鸡丁"
        assert count == 1
        # 没被过滤掉的候选只有 1 道, 天花板就是 1, 不该因为"不够 8 道"而放宽
        assert level == 0

    def test_candidate_count_is_pre_relaxation_size(self):
        """candidate_count 必须是放宽**前**的大小 —— 否则旧口径事后无法重算"""
        candidates = n_candidates(12, minutes=30)
        _, level, count, _band = run_pick(candidates, profile=make_profile(cook_cap=10))
        assert level == 1
        # 放宽前: cook_cap=10 挡掉全部 12 道 -> 0; 放宽后才是 12
        assert count == 0

    def test_band_size_is_the_real_choice_space(self):
        """band_size = 用户真正在其中抽签的那几道, 不是通过过滤的那几道

        candidate_count 会高估选择空间: 通过了过滤不等于真的进了抽签带。两个值分开
        才看得出"用户在几道菜里选"。
        """
        _, level, count, band_size = run_pick(n_candidates(POOL_MIN + 2))
        assert level == 0
        assert count == POOL_MIN + 2
        assert 1 <= band_size <= count

    def test_band_size_is_floored_by_padding(self):
        """🔴 band_size 有下限, 塌缩测不出来 —— 判塌缩必须用 natural_band_size

        `_random_band` 在真带不足 random_min_choices 时会按分数补齐, 于是
        `band_size >= random_min_choices` **恒成立** —— 数析实测过: 真带只有 2 道而
        band_size 是 3, 第 3 道比门槛低 7.9 分, 塌缩被 padding 完全掩盖。

        这里构造一个"真带只剩 1 道"的池子(5 道荤菜连吃三顿被扣 75 分), 验证两个数
        确实会分叉: band_size 被顶到下限, natural_band_size 如实报 1。
        任何"band_size >= N"形状的判据都会在这时候给出假绿。
        """
        settings = get_settings().decide
        history = RecentHistory(category_counts={"荤菜": 3})
        candidates = n_candidates(5, category="荤菜") + [
            make_candidate(id=99, name="唯一素菜", main="青菜", category="素菜")
        ]
        svc = make_service()
        out = svc._pick(  # noqa: SLF001
            candidates=candidates,
            profile=make_profile(),
            history=history,
            weather=WeatherContext(),
            inventory=set(),
            expiring=[],
            slot=MealSlot.DINNER,
            excluded=set(),
            today=TODAY,
        )
        assert out.natural_band_size == 1, "被扣分的 5 道荤菜不该还留在分差带里"
        # 补齐逻辑把 band_size 顶到了下限 —— 这正是"band_size >= 3 恒真"的原因
        assert out.band_size >= settings.random_min_choices
        assert out.band_size > out.natural_band_size


class TestBandSizesReachTheRow:
    """band_size / natural_band_size 必须真的写进 decision_log 的列

    为什么值得单独钉: 模型层"有这一列"和 `_persist` "传了这个值"是两件事 ——
    漏传的话列恒为 NULL, 而指标侧所有测试都是**手工造行**的, 一条都不会红。
    症状是 J6'/J7' 长期读到 None, 直到有人去看线上报表才发现两列从来没写过数。

    这里用假 db 直接抓 `DecisionLog(...)` 的入参, 不连数据库。
    """

    class _FakeDB:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        async def flush(self):
            return None

    @staticmethod
    async def _persist(**kwargs) -> object:
        db = TestBandSizesReachTheRow._FakeDB()
        svc = DecisionService.__new__(DecisionService)
        svc.db = db
        await svc._persist(  # noqa: SLF001
            user_id=1,
            picked=make_candidate(),
            result={"reason": "今天这个，不亏。"},
            slot=MealSlot.DINNER,
            weather=WeatherContext(),
            today=TODAY,
            **kwargs,
        )
        return db.rows[0]

    async def test_both_band_sizes_are_written(self):
        row = await self._persist(band_size=12, natural_band_size=5)
        assert row.band_size == 12
        assert row.natural_band_size == 5

    async def test_the_two_columns_are_not_substitutable(self):
        """两个数是不同的东西, 不能互相顶替

        natural_band_size 单独存在就是为了让 padding 掩盖不了的塌缩能被看见 ——
        如果哪天有人把它 coalesce 成 band_size, 判塌缩的判据就全假绿了。
        """
        row = await self._persist(band_size=3, natural_band_size=1)
        assert row.band_size == 3
        assert row.natural_band_size == 1

    async def test_missing_is_null_not_zero(self):
        """没测到就是 NULL, 不是 0 —— 0 是"抽签带空了"的缺陷信号, 缺值不能伪造它"""
        row = await self._persist()
        assert row.band_size is None
        assert row.natural_band_size is None
        # 显式写 0 要能存住, 否则缺陷信号被吞
        row = await self._persist(band_size=0, natural_band_size=0)
        assert row.band_size == 0
        assert row.natural_band_size == 0


# ------------------------------------------------------- 决策上下文落库 (R-07 半段)


class TestDecisionContext:
    """session_id / reroll_index / filters_snapshot —— 让"那一刻为什么没菜"能复现"""

    def test_session_id_is_cleaned_not_dropped(self):
        """去空白 + 截断到列宽, 但不做 UUID 校验

        格式不对也要存下来: 埋点宁可留下一个能查到"谁传错了"的值,
        也不要把整条会话链路静默丢成 NULL —— J1 的分母是会话数, 丢等于白做。
        """
        assert _clean_session_id("  abc-123  ") == "abc-123"
        assert _clean_session_id("") is None
        assert _clean_session_id(None) is None
        assert len(_clean_session_id("x" * 100)) == 36

    def test_filters_snapshot_captures_the_effective_filters(self):
        """快照要能回答"当时是按什么卡的我", 包括放宽之后实际生效的时间上限"""
        snap = _filters_snapshot(
            profile=make_profile(avoid=["花生"], cook_cap=15),
            slot=MealSlot.LATE_NIGHT,
            excluded={"番茄炒蛋"},
            intent=None,
            relaxed_level=1,
            cook_cap=None,
        )
        assert snap["meal_slot"] == MealSlot.LATE_NIGHT
        assert snap["cook_cap"] is None          # 第 1 档把时间上限松掉了
        assert snap["late_night_max_minutes"] == get_settings().decide.late_night_max_minutes
        assert snap["avoid_count"] == 1
        assert snap["excluded_count"] == 1
        assert snap["relaxed_level"] == 1

    def test_filters_snapshot_does_not_store_allergen_words(self):
        """快照里只放计数, 不放忌口/过敏的原词 —— 那是用户的健康隐私

        计数足够回答"是不是忌口把池子卡死了"; 真需要原文时去关联档案表,
        而不是把它复制进每一条决策快照里。
        """
        snap = _filters_snapshot(
            profile=make_profile(allergens=["花生"]),
            slot=MealSlot.DINNER,
            excluded=set(),
            intent=None,
            relaxed_level=0,
            cook_cap=60,
        )
        assert "花生" not in json.dumps(snap, ensure_ascii=False)
        assert snap["allergen_count"] == 1


# ------------------------------------------------------------ 结果卡: tools 透传 (展示用)


class TestToolsPassthrough:
    """需烤箱这类标签只是给结果卡看的, 不参与任何过滤/打分

    用户的路径是"看到烤箱才想起自己没有", 不是提前想到要去筛 —— 所以这里只做透传。
    """

    svc = make_service()

    def test_recipe_tools_are_carried_through(self):
        dish = make_candidate(tools=["oven"])
        result = self._result(dish)
        assert result["dish"]["tools"] == ["oven"]

    def test_multi_value_tools_are_not_truncated(self):
        """一道菜可能同时需要好几样厨具 —— 取值原样给全, 别写成 tools[0]

        库里存在 ["pot","steamer"] 这种多值行, 取第一个就把 steamer 丢了。
        """
        assert self._result(make_candidate(tools=["pot", "steamer"]))["dish"]["tools"] == [
            "pot",
            "steamer",
        ]

    def test_missing_tools_is_empty_list_not_absent(self):
        """前端按可空实现, 但下发空数组比缺字段更省心 —— 免得每个消费方都判 undefined"""
        result = self._result(make_candidate())
        assert result["dish"]["tools"] == []

    @staticmethod
    def _result(dish: Candidate) -> dict:
        return DecisionService._build_result(  # noqa: SLF001
            make_service(),
            picked=dish,
            reason="今天这个，不亏。",
            slot=MealSlot.DINNER,
            weather=WeatherContext(),
            inventory=set(),
            relaxed=False,
            moment=datetime(2026, 9, 23, 22, 30),
        )


# ------------------------------------------------------------ meal_slots 软惩罚 (R-11)


class TestMealSlotSoftPenalty:
    """meal_slots 覆盖率只有两成多: 做硬过滤会把候选砍到 1/4

    R-11 的落点只剩"影响排序"这么一点位置 —— 连加分都得压在 random_band 以内,
    否则它会从"软偏好"变成"抽签带独占"。见 MEAL_SLOT_MATCH_BONUS 处的新通则。
    """

    svc = make_service()
    profile = make_profile()
    history = RecentHistory()

    def score(self, dish: Candidate, slot: str) -> float:
        return self.svc._score(  # noqa: SLF001
            dish, self.profile, self.history, WeatherContext(), set(), [], slot
        )

    def test_match_scores_higher_than_mismatch(self):
        """餐次贴合有用, 但只是"更可能被抽到", 不是"必须/不许" """
        dish_match = make_candidate(meal_slots=["dinner"])
        dish_miss = make_candidate(meal_slots=["breakfast", "lunch"])
        assert self.score(dish_match, MealSlot.DINNER) > self.score(dish_miss, MealSlot.DINNER)

    def test_empty_meal_slots_is_not_a_restriction(self):
        """空值 = 不限制, 不奖不罚 —— 项目里所有场景字段的空语义都按这条来"""
        labeled = make_candidate(meal_slots=["dinner"])
        empty = make_candidate(meal_slots=[])
        gap = self.score(labeled, MealSlot.DINNER) - self.score(empty, MealSlot.DINNER)
        assert gap == pytest.approx(MEAL_SLOT_MATCH_BONUS)

    def test_mismatch_still_stays_in_pool(self):
        """不匹配并不出局 —— 这是 R-11 选软惩罚而不是硬过滤的全部意义"""
        dish = make_candidate(meal_slots=["breakfast", "lunch"])
        assert passes(dish, MealSlot.DINNER)
        assert (
            self.score(dish, MealSlot.DINNER)
            < self.score(make_candidate(meal_slots=["dinner"]), MealSlot.DINNER)
        )

    def test_binary_score_magnitude_stays_inside_random_band(self):
        """「命中/不命中」二元打分的幅度必须 <= random_band, 否则抽签带里只剩一侧的菜

        抽签按"距最优分的距离"选人, 不按绝对分。幅度超过 band 之后: 减分侧表现为准硬
        过滤, 加分侧表现为受加分的菜独占抽签带 —— 两者都让 32 道候选缩到个位数。
        """
        band = get_settings().decide.random_band
        assert abs(MEAL_SLOT_MATCH_BONUS) <= band
        assert abs(MEAL_SLOT_MISMATCH_PENALTY) <= band

    def test_late_night_whitelist_skips_the_meal_slot_score(self):
        """深夜里命中白名单的菜不吃餐次打分

        起因: 被白名单救回来的 29 道里, 17 道 meal_slots 是 ["breakfast","lunch"],
        明确不含 late_night。减分幅度已经压到 0 之后, 这条冲突自转平了; 留着它是为了
        防止哪天把减分加回来时旧账复发, 也顺带挡掉"晚面 -3 分"这种负优化。
        """
        noodle = make_candidate(category="面食", light=False, minutes=15,
                                meal_slots=["breakfast", "lunch"])
        assert self.svc._meal_slot_score(noodle, MealSlot.LATE_NIGHT) == 0.0  # noqa: SLF001
        # 白名单之外照常打分: 同样是明确不含 late_night, 荤菜该拿几分拿几分
        heavy = make_candidate(category="荤菜", meal_slots=["breakfast", "lunch"])
        assert self.svc._meal_slot_score(  # noqa: SLF001
            heavy, MealSlot.LATE_NIGHT
        ) == pytest.approx(MEAL_SLOT_MISMATCH_PENALTY)
        # 命中侧的加成同样被跳过 —— 深夜不该出现"因为多了一条标注就更受宠"的主食
        labeled_noodle = make_candidate(category="面食", meal_slots=["late_night"])
        assert self.svc._meal_slot_score(  # noqa: SLF001
            labeled_noodle, MealSlot.LATE_NIGHT
        ) == 0.0
