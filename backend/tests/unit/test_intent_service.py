"""口语诉求解析单测

同样不得依赖网络、不加载模型权重。重点验证两件事:
1. 规则兜底的各种说法都能正确解析(这是模型不可用时的默认路径);
2. 模型不可用/失败/把握不足时确实退回规则, 而不是把错误抛给用户。
"""

from __future__ import annotations

import pytest
from app.config import SystemOneSettings
from app.services.intent_service import (
    EMPTY_INTENT,
    MealIntent,
    MealIntentService,
    _from_model,
    _questions,
    _rule_understand,
    _verdict,
)
from app.services.system_one_service import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResult,
    SystemOneService,
)


class _Cand:
    """最小的候选菜替身, 只带 MealIntent 会用到的字段"""

    def __init__(self, name="番茄炒蛋", cuisine="家常", category="家常菜",
                 light=False, spice=0, minutes=15, ingredients=None):
        self.name = name
        self.cuisine = cuisine
        self.category = category
        self.light = light
        self.spice = spice
        self.minutes = minutes
        self.ingredients = ingredients or ["番茄", "鸡蛋"]

    @property
    def haystack(self) -> str:
        return " ".join([self.name] + self.ingredients)


# ------------------------------------------------------------------ 三态折叠

@pytest.mark.parametrize("p,expected", [(0.95, True), (0.1, False), (0.5, None)])
def test_verdict_three_states(p, expected):
    """中间地带必须返回 None(不采纳), 而不是强行二值化

    阈值已按语料拟合提到 0.91/0.20 —— 0.9 这种"看起来挺高"的值现在属于不确定区,
    这正是零样本权重在中文上置信度虚高的体现。
    """
    assert _verdict(p) is expected


# ------------------------------------------------------------------ 规则兜底

def test_rule_light():
    it = _rule_understand("今天想吃清淡点的")
    assert it.understood and it.require_light and it.source == "rule"


def test_rule_no_spicy():
    it = _rule_understand("别太辣")
    assert it.understood and it.max_spice == 0


def test_rule_mild_spicy_keeps_room():
    """「微辣」不能等同于「完全不辣」, 否则候选会被砍空"""
    assert _rule_understand("来个微辣的").max_spice == 1


def test_rule_rush():
    it = _rule_understand("赶时间，快点")
    assert it.understood and it.max_minutes == 20


def test_rule_fridge_and_meat():
    it = _rule_understand("冰箱里还有鸡蛋，今天吃素")
    assert it.prefer_fridge and it.avoid_meat


def test_rule_soup():
    assert _rule_understand("想喝汤").category == "汤"


def test_rule_extracts_avoid():
    it = _rule_understand("不要香菜，别放葱")
    assert it.understood
    assert "香菜" in it.avoid and "葱" in it.avoid


def test_rule_negation_is_not_a_positive_signal():
    """回归用例: 关键词匹配看不见否定

    "今天不想吃清淡的"里明明有"清淡"两个字, 意思却是反的。语料拟合时发现 21 条
    残余误判里有 5 条是这个 —— 修完纯规则的 FP 从 8 降到 3, 精确率 88% → 95%。
    """
    assert not _rule_understand("今天不想吃清淡的").require_light
    assert _rule_understand("别给我汤").category is None
    assert _rule_understand("不用着急, 慢慢来").max_minutes is None
    assert not _rule_understand("冰箱空了, 得买菜").prefer_fridge


def test_rule_negation_does_not_flip_exclusions():
    """排除型诉求本身就是否定形式, 不能再否定一次 —— 否则"不吃辣"会变成"吃辣"

    所以否定切除只作用于正向偏好(清淡/赶时间/冰箱/喝汤), 辣度和吃素仍在原文上匹配。
    """
    assert _rule_understand("不吃辣").max_spice == 0
    assert _rule_understand("今天吃素").avoid_meat
    assert "香菜" in _rule_understand("不要香菜").avoid


def test_rule_unknown_returns_not_understood():
    """匹配不到就老老实实说没听懂 —— 猜错的代价远大于没听懂"""
    it = _rule_understand("嗯……看看吧")
    assert not it.understood and not it.has_constraints


def test_empty_utterance():
    assert _rule_understand("   ") is EMPTY_INTENT


# ------------------------------------------------------------------ 约束生效

def test_allows_filters_by_light_and_spice():
    it = MealIntent(utterance="清淡不辣", understood=True, require_light=True, max_spice=0)
    assert it.allows(_Cand(light=True, spice=0))
    assert not it.allows(_Cand(light=False, spice=0))
    assert not it.allows(_Cand(light=True, spice=2))


def test_allows_filters_meat():
    it = MealIntent(utterance="吃素", understood=True, avoid_meat=True)
    assert it.allows(_Cand(name="番茄炒蛋", ingredients=["番茄", "鸡蛋"]))
    assert not it.allows(_Cand(name="红烧肉", ingredients=["五花肉"]))


def test_allows_filters_avoid_words():
    it = MealIntent(utterance="不要香菜", understood=True, avoid=["香菜"])
    assert not it.allows(_Cand(ingredients=["牛肉", "香菜"]))


def test_bonus_only_adds():
    """加分只做加法: 口语诉求是倾向, 不是命令"""
    it = MealIntent(utterance="想吃粤菜", understood=True, cuisine="粤菜", prefer_fridge=True)
    assert it.bonus(_Cand(cuisine="粤菜")) > 0
    assert it.bonus(_Cand(cuisine="川湘")) >= 0


def test_prefer_fridge_is_not_a_flat_bonus():
    """回归用例: prefer_fridge 不许回到 bonus() 里做全量加分

    它曾经在这里给"有食材的菜"一律 +6.0 —— `candidate.ingredients` 几乎对每道菜都
    非空, 于是每一道菜都拿到同样的 6.0。全量加分放进有预算上限的软偏好包, 等于用
    常数把预算烧光: 包被顶到 SOFT_PREFERENCE_CAP 之后早餐补偿 / meal_slots /
    库存命中三项同时失去区分度, 而方向还是反的(被挤掉的正是库存信号)。

    ❶ 压小幅度救不了 —— 只要它是全量的, 压到 1.0 照样烧掉预算且区分度仍为零。
    现在它改为放大 inventory 的命中数, 见 decision_service.PREFER_FRIDGE_MULTIPLIER。
    """
    it = MealIntent(utterance="冰箱里还有鸡蛋", understood=True, prefer_fridge=True)
    assert it.bonus(_Cand()) == 0.0


def test_has_constraints_false_when_empty():
    assert not MealIntent(utterance="随便").has_constraints


# ------------------------------------------------------------------ Jev 路径

def _model_result(**kw) -> SystemOneResult:
    answers = {
        "intent_type": ChoiceAnswer(choice=kw.get("intent_type", "describe_taste"),
                                    confidence=kw.get("intent_conf", 0.9)),
        "require_light": NoulAnswer(noul=kw.get("light", 0.1)),
        "avoid_spicy": NoulAnswer(noul=kw.get("spicy", 0.1)),
        "rush": NoulAnswer(noul=kw.get("rush", 0.1)),
        "use_fridge": NoulAnswer(noul=kw.get("fridge", 0.1)),
        "avoid_meat": NoulAnswer(noul=kw.get("meat", 0.1)),
        "want_soup": NoulAnswer(noul=kw.get("soup", 0.1)),
        "spice_tolerance": ScoreAnswer(score=kw.get("spice_score", 0.0),
                                       confidence=kw.get("spice_conf", 0.9)),
        "cuisine": ChoiceAnswer(choice=kw.get("cuisine", "无所谓"),
                                confidence=kw.get("cuisine_conf", 0.9)),
    }
    return SystemOneResult(provider="jev", answers=answers, ok=True)


def test_from_model_light_and_no_spicy():
    it = _from_model("清淡点别太辣", _model_result(light=0.95, spicy=0.9), 0.55)
    assert it.understood and it.require_light and it.max_spice == 0
    assert it.source == "jev"


def test_from_model_low_intent_type_confidence_does_not_block_others():
    """回归用例: 六选一的 intent_type 置信度低, 不该拖累判断正确的各条 noul

    曾经用 intent_type 的置信度当总闸, 结果它 0.25 就把整批判断全否了 ——
    而这个字段本身根本没参与构建意图。多路 Choice 天然比二值 Noul 置信度低。
    """
    it = _from_model("清淡点别太辣", _model_result(intent_conf=0.25, light=0.95, spicy=0.9), 0.55)
    assert it.source == "jev"
    assert it.require_light and it.max_spice == 0


def test_from_model_falls_back_only_when_everything_uncertain():
    """所有判断都落在不确定区时才整体退回规则"""
    it = _from_model(
        "今天想吃清淡点的",
        _model_result(light=0.5, spicy=0.5, rush=0.5, fridge=0.5, meat=0.5, soup=0.5,
                    spice_conf=0.2, cuisine_conf=0.2),
        0.55,
    )
    assert it.source == "rule"


def test_noul_baseline_too_high_is_not_adopted():
    """回归用例: Laya 多语言权重的中文 noul 基线明显偏高

    实测一句「吃清淡别太辣赶时间」, 没提到的"想吃素"拿到 0.715、"想喝汤"拿到
    0.682 —— 阈值若是 0.65 就会把它们误判成 True, 用户没说吃素却被塞一桌素菜。
    阈值提到 0.78 后这两个值落在中间地带 → 不采纳。
    """
    it = _model_result(0) if False else _from_model(
        "清淡别太辣", _model_result(light=0.96, spicy=0.94, meat=0.715, soup=0.682), 0.55
    )
    assert it.require_light and it.max_spice == 0
    assert not it.avoid_meat, "0.715 不该被判成「想吃素」"
    assert it.category is None, "0.682 不该被判成「想喝汤」"


def test_from_model_low_cuisine_confidence_only_drops_cuisine():
    """菜系没把握就只丢菜系这一条, 其余照常采纳"""
    it = _from_model("清淡点", _model_result(light=0.95, cuisine="粤菜", cuisine_conf=0.3), 0.55)
    assert it.source == "jev" and it.require_light and it.cuisine is None


def test_from_model_cuisine_other_is_ignored():
    it = _from_model("随便", _model_result(cuisine="无所谓"), 0.55)
    assert it.cuisine is None


def test_from_model_picks_cuisine():
    it = _from_model("想吃粤菜", _model_result(cuisine="粤菜"), 0.55)
    assert it.cuisine == "粤菜"


def test_from_model_rush_sets_cap():
    assert _from_model("赶时间", _model_result(rush=0.95), 0.55).max_minutes == 20


# ------------------------------------------------------------------ 逐维度融合

def test_model_beats_rule_when_rule_cannot_cover():
    """规则覆盖不到的说法("胃口不太好"), 模型判为真就采纳"""
    it = _from_model("最近胃口不太好", _model_result(light=0.95), 0.55)
    assert it.require_light and it.source == "jev"


def test_model_confident_false_vetoes_rule():
    """模型判"没这回事"(<= noul_reject)时, 规则的判断被否决

    这是 106 条语料拟合出来的行为: 让高把握的模型判断压过关键词, 才能把
    精确率从 63% 拉到 86%。规则说"清淡"但模型很确定用户没说, 就不该加这个约束。
    """
    it = _from_model("今天想吃清淡点的", _model_result(light=0.05), 0.55)
    assert it.source == "jev"
    assert not it.require_light, "模型判 0.05(明确否定)时不该沿用规则的 True"


def test_model_uncertain_falls_back_to_rule_per_dimension():
    """模型落在中间地带时, 规则补位 —— 逐维度, 不是整体退回"""
    it = _from_model("冰箱里还有鸡蛋", _model_result(fridge=0.5, light=0.05), 0.55)
    assert it.prefer_fridge, "模型没把握, 应该用规则的结果"
    assert not it.require_light, "这一条模型有把握(判假), 不该被规则覆盖"


def test_model_uncertain_spice_takes_rule_value():
    """辣度同理: 模型没把握就用规则抠出来的上限"""
    it = _from_model("别太辣", _model_result(spicy=0.5, light=0.05), 0.55)
    assert it.max_spice == 0


def test_source_is_rule_when_model_only_says_no():
    """模型只判"全都没有诉求"时, understood 应该是 False"""
    it = _from_model("随便", _model_result(), 0.55)
    assert not it.understood


def test_noul_instructions_must_ask_whether_user_said_it():
    """回归用例: Noul 的措辞必须是「用户**明确说出了**……」

    写成"用户想吃素吗"时, Laya 回答的是"这句话是否成立"而不是"用户说没说",
    于是用户根本没提到的诉求也能拿到 0.7。改措辞比调阈值有效得多 —— 这道
    断言就是防止有人手滑把措辞改回"想不想"句式。
    """
    from app.services.system_one_service import NoulQ

    noul_qs = [q for q in _questions().values() if isinstance(q, NoulQ)]
    assert len(noul_qs) == 6
    for q in noul_qs:
        assert "明确" in q.instructions, f"措辞退化了: {q.instructions}"


def test_from_model_still_extracts_rule_avoid():
    """「不要X」这类硬否定抠词仍交给规则更准, Jev 路径也要带上"""
    it = _from_model("清淡点，不要香菜", _model_result(light=0.9), 0.55)
    assert "香菜" in it.avoid


# ------------------------------------------------------------------ 服务降级

@pytest.mark.asyncio
async def test_understand_without_jev_uses_rule():
    svc = MealIntentService(settings=SystemOneSettings(enabled=False))
    it = await svc.understand("今天想吃清淡点的")
    assert it.source == "rule" and it.require_light


@pytest.mark.asyncio
async def test_understand_degrades_when_transport_fails():
    async def boom(*a, **kw):
        raise RuntimeError("boom")

    engine = SystemOneService(SystemOneSettings(enabled=True, provider="laya"))
    engine._call_laya = boom  # type: ignore[assignment]
    svc = MealIntentService(settings=SystemOneSettings(enabled=True, provider="laya"),
                            engine=engine)
    it = await svc.understand("今天想吃清淡点的")
    assert it.source == "rule" and it.require_light


@pytest.mark.asyncio
async def test_understand_empty_returns_empty_intent():
    svc = MealIntentService(settings=SystemOneSettings(enabled=True, provider="jev", api_key="k"))
    assert await svc.understand("   ") is EMPTY_INTENT


def test_to_dict_is_serializable():
    import json
    json.dumps(_rule_understand("清淡别太辣").to_dict(), ensure_ascii=False)
