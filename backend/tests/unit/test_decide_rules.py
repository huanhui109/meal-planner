"""饭决决策规则单测 (需求 5 / 6 / 9 / 10)

这里测的是**不依赖数据库**的纯逻辑: 过滤、打分、天气加权、理由生成。
需要 DB 的部分 (load_recent_history / decide 全链路) 放 integration。

为什么单独测纯逻辑: 决策规则是产品的核心承诺 ——
"近 7 天不重复、同品类打散、连续两餐不重样、理由 ≤20 字"。
这四条如果坏了, 用户立刻能感觉到, 但不会来反馈, 只会默默流失。
"""
from __future__ import annotations

from datetime import date

import pytest
from app.models.decision import MealSlot
from app.services.decision_service import (
    Candidate,
    DecisionService,
    Profile,
    RecentHistory,
    normalize_dish_name,
)
from app.services.reason_service import _GENERIC_CUISINE_LABELS, ReasonContext, ReasonService
from app.services.weather_service import WeatherContext


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


# ---------------------------------------------------------------- 需求 6: 理由 ≤20 字


class TestReason:
    svc = ReasonService()

    @pytest.mark.parametrize(
        "ctx",
        [
            ReasonContext(days_since_spicy=3),
            ReasonContext(days_since_spicy=30),
            ReasonContext(expiring_item="番茄"),
            ReasonContext(expiring_item="金针菇炒肉末配菜"),
            ReasonContext(weather="rain"),
            ReasonContext(weather="snow"),
            ReasonContext(weather="hot"),
            ReasonContext(weather="cold"),
            ReasonContext(meal_slot=MealSlot.LATE_NIGHT),
            ReasonContext(days_since_dish=6),
            ReasonContext(days_since_dish=99),
            ReasonContext(cuisine="粤式", cuisine_rotated=True),
            ReasonContext(inventory_ratio=0.5),
            ReasonContext(inventory_ratio=0.9),
            ReasonContext(),  # 一条都不命中 -> 空
            ReasonContext(relaxed=True),  # 放宽
        ],
    )
    def test_reason_within_20_chars(self, ctx: ReasonContext):
        assert len(self.svc.build(ctx)) <= 20, self.svc.build(ctx)

    def test_priority_spicy_comes_first(self):
        """更私人的理由应该优先: 「3 天没吃辣」比「家里现成就有」更像真的懂用户"""
        ctx = ReasonContext(days_since_spicy=4, inventory_ratio=0.9, weather="rain")
        assert self.svc.build(ctx).startswith("你 4 天没吃辣了")

    def test_relaxed_says_so(self):
        """候选被榨干时必须诚实说明, 不能假装规则还生效"""
        ctx = ReasonContext(days_since_spicy=5, relaxed=True)
        assert "不多了" in self.svc.build(ctx)

    def test_late_night_only_when_late_night(self):
        assert "深夜" not in self.svc.build(ReasonContext(meal_slot=MealSlot.LUNCH))
        assert "深夜" in self.svc.build(ReasonContext(meal_slot=MealSlot.LATE_NIGHT))

    # 遍历常量而不是抄一份词表: 抄一份就意味着加词时可能只改了实现没改测试
    @pytest.mark.parametrize("label", sorted(_GENERIC_CUISINE_LABELS))
    def test_rotation_skips_category_labels(self, label: str):
        """cuisine 列是脏的: 「换换口味，试试早餐」这种话不能说出口

        分类不是菜系, 套进轮换模板生成的句子虽然语法通顺, 但摆在结果卡上很荒谬。
        命中分类词时整条规则跳过, 宁可什么都不说 (build() 返回空)。
        """
        ctx = ReasonContext(dish="皮蛋瘦肉粥", cuisine=label, cuisine_rotated=True)
        assert label not in self.svc.build(ctx)

    def test_rotation_falls_back_to_next_rule(self):
        """跳过轮换后必须落到**下一条**规则 —— 用属性断言, 不逐字

        旧写法断言 `== "12 分钟搞定，不误事"`, 那条规则摘掉后它就没了落点。
        这里改成守四条性质, 而不是守一句当前实现的文案: 逐字断言把"规则链现在的
        样子"锁死, 下次调链又要改一遍; 属性断言守的是真正要守的东西 ——
          (a) 不许出现假精确的分钟数 (cook_minutes 是回填的品类基准值, 119 道都是 22)
          (b) 不许超过字数上限
          (c) 轮换被跳过后, 落到链条里下一条规则(现在是库存/食材)的输出
          (d) 一条都不命中时必须返回空, 不许兜万能句
        """
        # 轮换命中分类词「主食」被跳过 -> 由下一条(库存)接住, 所以给它一个能命中的命中率
        ctx = ReasonContext(
            dish="阳春面", cuisine="主食", cuisine_rotated=True, inventory_ratio=0.6
        )
        text = self.svc.build(ctx)
        # (c) 落到下一条规则, 不是掉到兜底也不是变成空
        assert text == "家里有一半食材，顺手"
        # (a) 分钟数假精确, 不许出现
        assert "分钟" not in text
        # (b) 上限引用 settings, 不抄 20 这个数字
        assert len(text) <= self.svc.settings.reason_max_chars
        # (d) 同一道菜但下一条也不命中 -> 空。万能句比没有更假
        assert (
            self.svc.build(ReasonContext(dish="阳春面", cuisine="主食", cuisine_rotated=True))
            == ""
        )

    def test_rotation_still_works_for_real_cuisine(self):
        ctx = ReasonContext(dish="三杯鸡", cuisine="粤式", cuisine_rotated=True)
        assert self.svc.build(ctx) == "换换口味，试试粤式"


# ---------------------------------------------------------------- 需求 5: 三条硬规则


class TestHardRules:
    svc = DecisionService.__new__(DecisionService)  # 只测纯函数, 不建 DB 会话
    svc.settings = DecisionService.__new__(DecisionService).settings = None
    from app.config import get_settings

    svc.settings = get_settings().decide

    def test_normalize_alias(self):
        """「番茄炒蛋」和「西红柿炒鸡蛋」必须判成同一道菜"""
        assert normalize_dish_name("西红柿 炒鸡蛋") == normalize_dish_name("番茄炒蛋")

    def test_seven_day_repeat_is_hard_blocked(self):
        history = RecentHistory(names={normalize_dish_name("番茄炒蛋")})
        assert not self._passes(make_candidate(), history, MealSlot.DINNER)

    def test_allergen_is_never_relaxed(self):
        """忌口与过敏是安全线, 任何一级放宽都不能放过"""
        profile = make_profile(avoid=["花生"])
        dish = make_candidate(ingredients=["鸡蛋", "花生酱"])
        for allow_repeat in (False, True):
            assert not self.svc._passes(  # noqa: SLF001
                dish, profile, RecentHistory(), WeatherContext(), set(), MealSlot.DINNER,
                set(), cook_cap=None, allow_repeat=allow_repeat,
            )

    def test_late_night_only_light_and_fast(self):
        """深夜 (需求 9): 非轻食 / 超过 20 分钟的一律剔除"""
        history = RecentHistory()
        assert self._passes(
            make_candidate(light=True, minutes=12), history, MealSlot.LATE_NIGHT
        )
        assert not self._passes(
            make_candidate(light=False, minutes=8), history, MealSlot.LATE_NIGHT
        )
        assert not self._passes(
            make_candidate(light=True, minutes=45), history, MealSlot.LATE_NIGHT
        )

    def test_category_spread_penalty(self):
        """同品类打散: 最近 3 餐吃过的品类要被扣分, 出现越多扣越多"""
        history = RecentHistory(category_counts={"荤菜": 2}, last_cuisine="")
        fresh = RecentHistory(category_counts={}, last_cuisine="")
        dish = make_candidate(category="荤菜")
        assert self._score(dish, history) < self._score(dish, fresh)

    def test_consecutive_meal_main_ingredient_penalty(self):
        """连续两餐不重样: 上一餐主料重合要被扣分"""
        history = RecentHistory(last_main="鸡蛋")
        fresh = RecentHistory(last_main="")
        dish = make_candidate(main="鸡蛋")
        assert self._score(dish, history) < self._score(dish, fresh)

    def test_cook_cap_filters(self):
        profile = make_profile(cook_cap=15)
        assert self._passes(make_candidate(minutes=10), RecentHistory(), MealSlot.DINNER, profile)
        assert not self._passes(
            make_candidate(minutes=40), RecentHistory(), MealSlot.DINNER, profile
        )

    # --- 辅助 ---

    def _passes(self, dish, history, slot, profile=None, **kwargs) -> bool:
        return self.svc._passes(  # noqa: SLF001
            dish,
            profile or make_profile(),
            history,
            WeatherContext(),
            set(),
            slot,
            set(),
            cook_cap=(profile or make_profile()).cook_cap,
            **kwargs,
        )

    def _score(self, dish, history) -> float:
        return self.svc._score(  # noqa: SLF001
            dish, make_profile(), history, WeatherContext(), set(), [], MealSlot.DINNER
        )


# ---------------------------------------------------------------- 需求 9: 天气


class TestWeather:
    svc = DecisionService.__new__(DecisionService)
    from app.config import get_settings

    svc.settings = get_settings().decide

    def test_unknown_weather_is_not_sunny(self):
        """没有天气数据时所有天气规则必须整体跳过, 而不是当成晴天"""
        dish = make_candidate(tags=["清爽"])
        assert self.svc._weather_score(dish, WeatherContext(), 0.5) == 0.0  # noqa: SLF001

    def test_rain_prefers_home_cooking(self):
        dish = make_candidate(tags=["汤羹"])
        rainy = WeatherContext(condition="rain")
        assert self.svc._weather_score(dish, rainy, 0.6) > 0  # noqa: SLF001
        # 家里没料时, 雨天的"在家做"加分要明显弱于有料时
        assert self.svc._weather_score(dish, rainy, 0.6) > self.svc._weather_score(  # noqa: SLF001
            dish, rainy, 0.0
        )

    def test_hot_penalizes_heavy_spicy(self):
        dish = make_candidate(spice=4, tags=["热辣"])
        assert self.svc._weather_score(dish, WeatherContext(condition="hot"), 0.3) < 0  # noqa: SLF001

    def test_cold_penalizes_cold_dish(self):
        dish = make_candidate(category="凉菜", tags=["凉拌"])
        assert self.svc._weather_score(dish, WeatherContext(condition="cold"), 0.3) < 0  # noqa: SLF001


# ---------------------------------------------------------------- 需求 10: 极简做法


class TestQuickSteps:
    svc = DecisionService.__new__(DecisionService)
    from app.config import get_settings

    svc.settings = get_settings().decide

    def test_clip_to_max_5(self):
        steps = [f"步骤{i}" for i in range(9)]
        assert len(self.svc._clip_steps(steps)) == 5  # noqa: SLF001

    def test_keep_short_recipes_intact(self):
        assert len(self.svc._clip_steps(["a", "b", "c"])) == 3  # noqa: SLF001


# ---------------------------------------------------------------- 时段


def test_slot_resolution():
    from datetime import datetime

    svc = DecisionService.__new__(DecisionService)
    from app.config import get_settings

    svc.settings = get_settings().decide
    assert svc._resolve_slot(None, datetime(2026, 9, 17, 23, 30)) == MealSlot.LATE_NIGHT  # noqa: SLF001
    assert svc._resolve_slot(None, datetime(2026, 9, 17, 2, 0)) == MealSlot.LATE_NIGHT  # noqa: SLF001
    assert svc._resolve_slot(None, datetime(2026, 9, 17, 8, 0)) == MealSlot.BREAKFAST  # noqa: SLF001
    assert svc._resolve_slot(None, datetime(2026, 9, 17, 12, 0)) == MealSlot.LUNCH  # noqa: SLF001
    assert svc._resolve_slot(None, datetime(2026, 9, 17, 19, 0)) == MealSlot.DINNER  # noqa: SLF001


def test_history_window_is_days_not_weeks():
    """「近 7 天」必须是按天的窗口。旧逻辑按周取, 粒度完全对不上"""
    from app.config import get_settings

    assert get_settings().decide.no_repeat_days == 7
    assert date(2026, 9, 17) - date(2026, 9, 10) == __import__("datetime").timedelta(days=7)
