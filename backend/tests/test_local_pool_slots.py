"""离线池 meal_slots 的口径钉子 (R-11)

为什么单独一个文件:
  test_decide_parity.py 钉的是**常量** (MEAL_SLOT_MATCH_BONUS 两端同名同值), 钉不住**数据**。
  本地池这 62 道是人手工维护的, 任何一种"顺手把 null 改成 []"、"补一个没在库里核对过的
  餐次"、"把未标注当成不匹配"都不会让常量断言变红 —— 症状是断网用户和联网用户拿不到
  同一套加分, 而这正是这条规则存在的唯一理由。

这里守三件事:
  1. slots 字段本身: 每道菜都有, 且是 None 或合法餐次的非空子集
  2. null = 不限制: 经 _from_pool 变成空 list 后, 打分不奖不罚 (不是"哪顿都不合适")
  3. 夜宵白名单豁免: 主食/面食在深夜跳过餐次打分, 与 shared/decide.ts 的 mealSlotScore 一致

不在这里做的事: 不连数据库校验取值。真值来自 recipe.meal_slots, 但断言"库里现在是什么"
会让这份测试随库里数据漂移 —— 库变了应该是人来决定要不要跟, 而不是测试替他决定。
"""
from __future__ import annotations

import pytest
from app.data.local_pool import LOCAL_DISHES
from app.models.decision import MealSlot
from app.services.decision_service import (
    LATE_NIGHT_EXTRA_CATEGORIES,
    MEAL_SLOT_MATCH_BONUS,
    MEAL_SLOT_MISMATCH_PENALTY,
    Candidate,
    DecisionService,
)

# db 只用于数据库查询, 这里只调纯打分方法, 传 None 不会碰到它
SERVICE = DecisionService(db=None)  # type: ignore[arg-type]


def _pool_candidate(name: str) -> Candidate:
    item = next(x for x in LOCAL_DISHES if x["name"] == name)
    return DecisionService._from_pool(item)


def test_every_dish_carries_a_slots_field():
    """62 道都必须带 slots: 缺字段说明有人手改了真源却没走生成器"""
    for item in LOCAL_DISHES:
        assert "slots" in item, f"「{item['name']}」缺 slots 字段"


@pytest.mark.parametrize("item", LOCAL_DISHES, ids=[x["name"] for x in LOCAL_DISHES])
def test_slots_is_null_or_a_non_empty_meal_slot_subset(item):
    """slots 只能是 None (不限制) 或合法餐次的非空子集 —— 空数组会被读成"不限制",
    和 None 混淆, 而它长得像"我标过了, 结果是空的", 所以不许出现"""
    if item["slots"] is None:
        return
    assert isinstance(item["slots"], list) and item["slots"], f"「{item['name']}」slots 不能是空数组"
    for slot in item["slots"]:
        assert slot in MealSlot.ALL, f"「{item['name']}」slots 含非法餐次 {slot}"


def test_null_slots_means_no_restriction_not_no_meal():
    """null 的语义: 经 _from_pool 变空 list, 打分不奖不罚

    这是全文件最重要的一条。空值一旦被读成"不匹配", 52 道未标注的菜会在每一餐被
    MISMATCH_PENALTY 压一遍 —— 规则就从"让汤羹晚饭容易出"翻成"只让那 10 道出"。
    """
    unannotated = [x for x in LOCAL_DISHES if x["slots"] is None]
    assert len(unannotated) == 52, "未标注的道数变了, 说明数据被改过 —— 确认是有意为之"
    for item in unannotated:
        c = DecisionService._from_pool(item)
        assert c.meal_slots == []
        for slot in MealSlot.ALL:
            assert SERVICE._meal_slot_score(c, slot) == 0.0


def test_annotated_dish_scores_bonus_only_on_its_own_slot():
    """标了 dinner 的菜: 晚饭加分, 别的餐次不奖不罚 (减分侧幅度是 0)"""
    c = _pool_candidate("冬瓜排骨汤")
    assert c.meal_slots == ["dinner"]
    assert SERVICE._meal_slot_score(c, MealSlot.DINNER) == pytest.approx(MEAL_SLOT_MATCH_BONUS)
    for slot in (MealSlot.BREAKFAST, MealSlot.LUNCH, MealSlot.LATE_NIGHT):
        assert SERVICE._meal_slot_score(c, slot) == pytest.approx(MEAL_SLOT_MISMATCH_PENALTY)


def test_late_night_whitelist_dishes_skip_slot_scoring():
    """夜宵白名单 (主食/面食) 完全跳过餐次打分: 白名单是人工裁决, 优先级更高

    否则刚被白名单放进夜宵池的面, 又会因为标了 ["breakfast","lunch"] 被压回去 ——
    两个改动互相抵消。shared/decide.ts 的 mealSlotScore 第一行是同一个分支。
    """
    whitelisted = [
        x for x in LOCAL_DISHES if x["category"] in LATE_NIGHT_EXTRA_CATEGORIES and x["slots"]
    ]
    assert whitelisted, "离线池里没有标了 slots 的主食/面食, 这条豁免就没被覆盖到"
    for item in whitelisted:
        c = DecisionService._from_pool(item)
        assert SERVICE._meal_slot_score(c, MealSlot.LATE_NIGHT) == 0.0
