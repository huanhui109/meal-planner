"""R-11 验收⑦: 软偏好不许把抽签带压塌

为什么单独一个文件 + 为什么要几百道候选:
    这条量的是"几百道菜一起打完分之后, 抽签带还剩多少道"。塌缩是**相对 random_band**
    发生的, 十几道候选的池子看不出来 —— 所以这里铺一批菜跑 N 次, 看分布而不是看单点。

它钉住两件事:
    1. 当前幅度 (3/0) 下: 抽签带没塌, 也没有哪个品类独占;
    2. 一旦有人把幅度抬到 random_band 之上: 上面两条**必须**变差。
       第 2 条是反向断言, 也是这条常量存在的理由 —— 抬上去而不塌,
       说明第 1 条根本没测到点上。

真实库上的对照 (只读脚本实测, 晚饭档 N=500, 342 道):
    +12/-20 → band_size 恒为 9, 汤羹占 66.2%, 只剩 3 个品类能被抽到
    +3/0    → band_size 60, 汤羹占 11.0%, 7 个品类, 与自然占比基本一致
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import date

import pytest
from app.models.decision import MealSlot
from app.services import decision_service as ds
from app.services.decision_service import (
    Candidate,
    DecisionService,
    Profile,
    RecentHistory,
)
from app.services.weather_service import WeatherContext

# 品类分布照真实库的比例铺: 汤羹是小众品类, 正常只占个位数百分比。
# CATEGORY_MIX 是直接的道数, 不是百分比 —— 之前这里又乘了一遍 POOL_SIZE/100,
# 于是铺出 1000 多道, 谁也没发现。
CATEGORY_MIX = [
    ("荤菜", 150),
    ("素菜", 70),
    ("主食", 40),
    ("面食", 25),
    ("汤羹", 25),
    ("凉菜", 20),
]
N_SAMPLES = 200
TODAY = date(2026, 9, 23)

# 反例幅度: 明显超过 random_band (5.0), 复现第一版 12/-20 的塌缩
OVERSIZE_BONUS = 12.0
OVERSIZE_PENALTY = -20.0
# "拆掉封顶"用的值: 要大到让软偏好包完全不封顶, 才看得出没有封顶时什么样
NO_CAP = 999.0


def _pool() -> list[Candidate]:
    """铺一批候选: 约两成带 meal_slots 标注 (与真实覆盖率一致), 其中一半明确不含晚餐"""
    dishes: list[Candidate] = []
    idx = 0
    for category, count in CATEGORY_MIX:
        for i in range(count):
            meal_slots = []
            if idx % 5 == 0:
                meal_slots = ["dinner"] if idx % 10 == 0 else ["breakfast", "lunch"]
            dishes.append(
                Candidate(
                    id=idx,
                    name=f"{category}-{i}",
                    cuisine="家常",
                    category=category,
                    main=f"主料{idx}",
                    minutes=15 + (idx % 5) * 5,
                    calories=300,
                    difficulty=2,
                    spice=idx % 3,
                    light=False,
                    cover="下饭",
                    tags=["快手"],
                    flavors=[],
                    ingredients=[f"食材{idx}"],
                    steps=["备菜", "下锅", "出锅"],
                    meal_slots=meal_slots,
                )
            )
            idx += 1
    return dishes


def _sample(svc: DecisionService, candidates: list[Candidate], n: int = N_SAMPLES):
    bands: list[int] = []
    cats: Counter = Counter()
    for _ in range(n):
        out = svc._pick(  # noqa: SLF001
            candidates=candidates,
            profile=Profile(),
            history=RecentHistory(),
            weather=WeatherContext(),
            inventory=set(),
            expiring=[],
            slot=MealSlot.DINNER,
            excluded=set(),
            today=TODAY,
        )
        bands.append(out.band_size)
        cats[out.candidate.category] += 1
    return statistics.median(bands), cats, n


class TestBandHealth:
    svc = DecisionService.__new__(DecisionService)
    from app.config import get_settings

    svc.settings = get_settings().decide

    def test_soft_preference_keeps_the_band_wide(self):
        """当前幅度下抽签带必须还够宽 —— 用户是在这个带里抽签, 不是在一个人的意志里"""
        candidates = _pool()
        band_median, cats, n = _sample(self.svc, candidates)

        assert len(candidates) > 50, "样本量太小, 塌缩看不出来"
        # 合成数据里幅度靠的是这条断言: 健康时带是 100+ 道, 塌缩时只剩十几道
        assert band_median >= 20, f"抽签带塌到 {band_median} 道, 这不是软偏好而是准硬过滤"

        # 品类不能独占。判据不是"占比绝对值" —— 荤菜本来就占池子四成半,
        # 抽得多是正常的; 要看的是**相对池子里的占比有没有被放大**。
        baseline = Counter(c.category for c in candidates)
        for category, hits in cats.items():
            share = hits / n
            natural = baseline[category] / len(candidates)
            assert share <= max(natural * 2, 0.15), (
                f"{category} 池子里占 {natural:.0%}, 却抽出了 {share:.0%} "
                f"—— 这不是软偏好, 是拿 meal_slots 的标注运气替用户做了排除"
            )
        # 验收⑦ 原文的硬下限: 汤羹是小众品类, 被抬到三分之一就说明带塌了
        soup_share = cats["汤羹"] / n
        assert soup_share <= 0.35, f"汤羹占 {soup_share:.0%}, 晚饭三顿有两顿是汤"

    def test_over_band_amplitude_would_collapse_it(self):
        """反例: 幅度抬过 random_band **且拆掉软偏好包封顶**, 带就必须塌下来

        第一版就是这么写坏的: 12/-20 的绝对值看着不大, 但因为超过了 band, 效果等于硬过滤 ——
        留给用户选择的就那么几道, 谁都看得出"这个 App 就这几道菜"。

        ⚠️ 为什么必须连 SOFT_PREFERENCE_CAP 一起抬:
        软偏好包封顶上线之后, 只抬 meal_slots 幅度**不会塌了** —— 实测 121 vs 121,
        因为那 12 分进包之后被整包压回 5 分。这不是反例失效, 是封顶在干活。
        所以这里把封顶一并拆掉, 才能复现"没有封顶时是什么样"。
        """
        candidates = _pool()
        healthy_band, _, _ = _sample(self.svc, candidates, n=40)

        original = (
            ds.MEAL_SLOT_MATCH_BONUS,
            ds.MEAL_SLOT_MISMATCH_PENALTY,
            ds.SOFT_PREFERENCE_CAP,
        )
        ds.MEAL_SLOT_MATCH_BONUS = OVERSIZE_BONUS
        ds.MEAL_SLOT_MISMATCH_PENALTY = OVERSIZE_PENALTY
        ds.SOFT_PREFERENCE_CAP = NO_CAP
        try:
            collapsed_band, _, _ = _sample(self.svc, candidates, n=40)
        finally:
            (
                ds.MEAL_SLOT_MATCH_BONUS,
                ds.MEAL_SLOT_MISMATCH_PENALTY,
                ds.SOFT_PREFERENCE_CAP,
            ) = original

        assert collapsed_band < healthy_band, (
            f"幅度抬到 {OVERSIZE_BONUS}/{OVERSIZE_PENALTY} 且拆掉封顶之后抽签带没有变小 "
            f"({collapsed_band} vs {healthy_band}), 说明上一个用例没测到点上"
        )

    def test_soft_preference_cap_is_what_holds_the_band(self):
        """只抬幅度、不动封顶: 带不许塌 —— 这条钉的是"封顶是承重的那个"

        和上面那一条是一对: 上一条证明"没了封顶会塌", 这条证明"有封顶就不塌"。
        只留上一条会让人以为幅度合规就够了 —— 而 3.0 这个数字正是靠封顶兜底的:
        单项合规挡不住几笔叠起来穿(早餐 4.5 + 库存 4.0 = 8.5)。

        ⚠️ 2026-09-23 这条被**翻转过两次**, 两个方向都留个记录, 免得第三次照抄:
          · 曾经翻成"抬幅度**必须**塌", 那时餐次贴合/早餐补偿被移出了软偏好包
            (所谓"场景层", 即方案「叠加 7.5」)。包外不受封顶约束, 抬幅度当然塌。
          · 该方案已被回退 —— 门禁改成结果判红后, 它在 4 场景 × 补标前后 8 格里
            挂了 2 格(荤菜x1/补标后 natural_band=17、prefer_fridge/补标后=13)。
            回退后餐次贴合重回包内, 本条也跟着翻回来。
        ⇒ **改这条之前先看 `decision_service._score()` 里餐次贴合在包内还是包外** ——
          断言方向取决于实现位置, 不看实现对着翻转就是给绿灯。
        """
        candidates = _pool()
        healthy_band, _, _ = _sample(self.svc, candidates, n=40)

        original = (ds.MEAL_SLOT_MATCH_BONUS, ds.MEAL_SLOT_MISMATCH_PENALTY)
        ds.MEAL_SLOT_MATCH_BONUS = OVERSIZE_BONUS
        ds.MEAL_SLOT_MISMATCH_PENALTY = OVERSIZE_PENALTY
        try:
            capped_band, _, _ = _sample(self.svc, candidates, n=40)
        finally:
            ds.MEAL_SLOT_MATCH_BONUS, ds.MEAL_SLOT_MISMATCH_PENALTY = original

        assert capped_band >= healthy_band * 0.8, (
            f"幅度抬到 {OVERSIZE_BONUS}/{OVERSIZE_PENALTY} 后带从 {healthy_band} 掉到 "
            f"{capped_band} —— SOFT_PREFERENCE_CAP 没兜住。若餐次贴合确实已移出包外, "
            f"本条断言方向要跟着翻, 但那就得先过门禁的 8 格结果判红"
        )

    def test_binary_score_stays_below_random_band(self):
        """幅度 < random_band 的兜底断言: 这条钉住了 3.0 这个数字的上界"""
        band = ds.get_settings().decide.random_band
        assert abs(ds.MEAL_SLOT_MATCH_BONUS) < band
        assert abs(ds.MEAL_SLOT_MISMATCH_PENALTY) < band


if __name__ == "__main__":  # 手动跑: python -m pytest 之外, 想看数字时用
    svc = TestBandHealth.svc
    mid, cats, n = _sample(svc, _pool())
    print("band 中位数", mid, "品类分布", dict(cats.most_common()))
    raise SystemExit(pytest.main([__file__, "-q"]))
