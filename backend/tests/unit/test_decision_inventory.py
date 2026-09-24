"""R-09 库存打分归一化: 命中数排序 + 命中率供天气/文案

这里守的是"两个语义分开"这件事本身, 以及那条最容易被人忘掉的幅度上限。
触发率级别的对数由 data-analyst 的基线脚本守(三组快照 + 菜名指纹), 那边更权威。
"""
from __future__ import annotations

import pytest
from app.config import get_settings
from app.models.decision import MealSlot
from app.services.decision_service import (
    INVENTORY_HITS_FULL,
    INVENTORY_SCORE_CAP,
    SOFT_PREFERENCE_CAP,
    Candidate,
    DecisionService,
    Profile,
    RecentHistory,
)
from app.services.intent_service import MealIntent
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
        spice=2,
        light=False,
        cover="下饭",
        tags=[],
        flavors=[],
        ingredients=[],
        steps=["a", "b", "c"],
    )
    base.update(kwargs)
    return Candidate(**base)


class TestInventory:
    svc = DecisionService.__new__(DecisionService)
    from app.config import get_settings

    svc.settings = get_settings().decide

    def test_ratio_is_still_hits_over_own_ingredients(self):
        """命中率口径一行没改 —— 天气加分和「交给外卖吧」都指着它"""
        dish = make_candidate(ingredients=["鸡蛋", "番茄", "盐"])
        assert self.svc._inventory_ratio(dish, {"鸡蛋"}) == pytest.approx(1 / 2)  # noqa: SLF001
        assert self.svc._inventory_ratio(dish, set()) == 0.0  # noqa: SLF001
        # 调味料不算"家里有"
        assert self.svc._inventory_ratio(dish, {"盐"}) == 0.0  # noqa: SLF001

    def test_hits_is_absolute_not_relative(self):
        """命中数不看这道菜有多少食材 —— 这才是"奖励你家有的菜"的意思"""
        small = make_candidate(ingredients=["鸡蛋", "番茄"])
        big = make_candidate(
            ingredients=["鸡蛋", "番茄", "土豆", "青椒", "豆腐", "面粉"]
        )
        assert self.svc._inventory_hits(small, {"鸡蛋"}) == 1  # noqa: SLF001
        assert self.svc._inventory_hits(big, {"鸡蛋", "番茄", "土豆"}) == 3  # noqa: SLF001

    def test_simple_dishes_no_longer_win_by_being_simple(self):
        """核心: 2 样食材录中 1 样, 不该赢过 6 样食材录中 3 样

        旧口径下前者 1/2=50%、后者 3/6=50% 打平, 而食材越少越容易凑满 ——
        实际效果就是"越简单的菜越靠前"。
        """
        simple = make_candidate(ingredients=["鸡蛋", "番茄"])
        rich = make_candidate(ingredients=["鸡蛋", "番茄", "土豆", "青椒", "豆腐", "面粉"])
        # 库存按 docstring 给: 简单菜只录中 1 样、复杂菜录中 3 样。
        # ⚠️ 别顺手把「番茄」也放进库存 —— 那样简单菜命中 2 样, 在 FULL=2 下两道菜
        # 同时触顶(都是 5.0), 断言就从"简单菜不再赢"退化成"两边相等", 什么都测不到。
        inventory = {"鸡蛋", "土豆", "青椒"}
        assert self.svc._inventory_score(simple, inventory, []) < (  # noqa: SLF001
            self.svc._inventory_score(rich, inventory, [])  # noqa: SLF001
        )

    def test_score_is_continuous_not_binary(self):
        """录中 1 样就该比没录中强, 但不必一步登天 —— 连续型才不会切带"""
        dish = make_candidate(ingredients=["鸡蛋", "番茄", "土豆"])
        zero = self.svc._inventory_score(dish, set(), [])  # noqa: SLF001
        one = self.svc._inventory_score(dish, {"鸡蛋"}, [])  # noqa: SLF001
        full = self.svc._inventory_score(dish, {"鸡蛋", "番茄", "土豆"}, [])  # noqa: SLF001
        assert zero == 0.0
        assert zero < one < full

    def test_family_bonus_never_exceeds_the_cap(self):
        """命中加分 + 临期加分合起来也不能超过上限

        两笔都是库存派生量, 分开各封 5 分叠起来是 10, 照样能把抽签带切成两半。
        """
        dish = make_candidate(ingredients=["鸡蛋", "番茄", "土豆"])
        inventory = {"鸡蛋", "番茄", "土豆"}
        both = self.svc._inventory_score(dish, inventory, ["鸡蛋"])  # noqa: SLF001
        assert both <= INVENTORY_SCORE_CAP

    def test_cap_is_inside_random_band(self):
        """上限必须 <= random_band —— 与 meal_slots 同一条通则"""
        assert INVENTORY_SCORE_CAP <= get_settings().decide.random_band

    def test_full_marks_need_full_constant(self):
        assert self.svc._inventory_score(  # noqa: SLF001
            make_candidate(ingredients=["a", "b", "c"]), {"a", "b", "c"}, []
        ) == pytest.approx(min(self.svc.settings.score_inventory, INVENTORY_SCORE_CAP))
        # 2 是 data-analyst A22 的定标值 (真库 342 道实测), 不是初值:
        # FULL=3 时真实小冰箱只有 1 道菜(0.3%)能拿满, R-09 等于没接线。
        assert INVENTORY_HITS_FULL == 2

    def test_prefer_fridge_amplifies_hits_not_a_flat_bonus(self):
        """prefer_fridge 放大的是**命中数**, 不是给每道菜加同一个常数

        回归用例: 它曾经在 MealIntent.bonus() 里给"有食材的菜"一律 +6.0 —— 因为
        `ingredients` 几乎对每道菜都非空, 那就是一笔**全量加分**, 整个软偏好包被
        烧到封顶值, 包里其他项(早餐补偿 / meal_slots / 库存命中)一起失去区分度。

        改成放大命中数之后必须同时成立:
          命中 0 样 → 仍是 0 分 (放大 0 还是 0, 不许白送分)
          命中 1 样 < 命中 2 样 (保住连续型, 不许退化回"有食材就满分")
          同一道菜, 有这个意图时严格更强 (信号真的接上了)
        """
        dish = make_candidate(ingredients=["鸡蛋", "番茄"])
        intent = MealIntent(utterance="冰箱里还有鸡蛋", understood=True, prefer_fridge=True)
        zero = self.svc._inventory_score(dish, set(), [], intent)  # noqa: SLF001
        one = self.svc._inventory_score(dish, {"鸡蛋"}, [], intent)  # noqa: SLF001
        full = self.svc._inventory_score(dish, {"鸡蛋", "番茄"}, [], intent)  # noqa: SLF001
        assert zero == 0.0
        assert zero < one < full
        assert one > self.svc._inventory_score(dish, {"鸡蛋"}, [])  # noqa: SLF001
        # 放大之后仍受家族封顶兜着 —— 允许触顶, 但绝不允许穿透
        assert full <= INVENTORY_SCORE_CAP

    def test_prefer_fridge_does_not_flatten_the_soft_pack(self):
        """P0 验收口径本身: 开了 prefer_fridge, 不同候选的软包贡献不能全是同一个数

        全量加分(+6.0 对每个"有食材"的候选都成立)会把包烧到 SOFT_PREFERENCE_CAP,
        于是库存命中 / 餐次贴合 / intent 三笔一起失效 —— 不管冰箱里有什么、不管
        用户说了什么, 包贡献都是同一个常数。这条守的是"包还在分化"。

        两道菜只在**库存命中数**上不同(其余字段全部相同), 所以总分的差只可能来自
        软偏好包里的库存那一项:
          总分有差  ⇒ 包没被烧平(包外各项按构造是相等的)
          总分无差  ⇒ 包被顶到封顶值了, 回归
        """
        intent = MealIntent(utterance="冰箱里还有鸡蛋", understood=True, prefer_fridge=True)
        inventory = {"鸡蛋"}
        kwargs = dict(
            profile=Profile(spice_level=2),
            history=RecentHistory(),
            weather=WeatherContext(),
            inventory=inventory,
            expiring=[],
            slot=MealSlot.DINNER,
        )
        no_hit = self.svc._score(  # noqa: SLF001
            make_candidate(name="冰箱里一样都没有", ingredients=["豆腐", "青椒"]),
            intent=intent, **kwargs
        )
        one_hit = self.svc._score(  # noqa: SLF001
            make_candidate(name="冰箱里有鸡蛋", ingredients=["鸡蛋", "青椒"]),
            intent=intent, **kwargs
        )
        gap = one_hit - no_hit
        # 不只是"不为零", 还要有量级: 0.01 的差异在 5 分的抽签带里等于没有
        assert gap > 0.5, f"软包没有分化, 差 {gap}"
        # 但也不能突破包的上限 —— 分化是靠幅度换来的, 不是靠绕过封顶
        assert gap <= SOFT_PREFERENCE_CAP

    def test_ranking_uses_hits_while_weather_uses_ratio(self):
        """端到端: 同一个候选, 排序分与天气分取自两个不同的量"""
        dish = make_candidate(
            ingredients=["鸡蛋", "番茄", "土豆", "青椒", "豆腐", "面粉"],
            tags=["汤羹"],
        )
        inventory = {"鸡蛋", "番茄", "土豆"}
        scored = self.svc._score(  # noqa: SLF001
            dish, Profile(spice_level=2), RecentHistory(),
            WeatherContext(condition="rain"), inventory, [], MealSlot.DINNER,
        )
        # 排序只吃到 min(hits,FULL)/FULL 那一份, 天气吃到 ratio 那一份
        assert scored > self.svc._inventory_score(dish, inventory, [])  # noqa: SLF001
