"""Unit tests for the 饭决 skill contract (strict reply validation).

This is the guarantee behind "every call only emits meal-planner content": a
reply that is prose, has extra fields, wrong types, invented keys or a
mismatched request_id must be REJECTED, never saved.
"""
from __future__ import annotations

import json

import pytest
from app.services import fandecide_skill_contract as skill

RID = "11111111-1111-1111-1111-111111111111"


def _reply(**over) -> str:
    base = {
        "request_id": RID, "phase": "proposal",
        "candidate_keys": ["recipe:101"], "reason": "单人清淡快手",
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


def test_accepts_a_minimal_valid_proposal():
    result = skill.validate_reply(_reply(), request_id=RID)
    assert result["request_id"] == RID
    assert result["phase"] == "proposal"
    assert result["candidate_keys"] == ["recipe:101"]
    assert result["reason"] == "单人清淡快手"
    assert "context" not in result


def test_accepts_a_fenced_block_and_strips_the_fence():
    text = "```json\n" + _reply() + "\n```"
    assert skill.validate_reply(text, request_id=RID)["candidate_keys"] == ["recipe:101"]


def test_accepts_an_optional_context_patch():
    result = skill.validate_reply(
        _reply(context={"mode": "takeout", "max_spice": 0}), request_id=RID,
    )
    assert result["context"] == {"mode": "takeout", "max_spice": 0}


def test_accepts_a_failure_reply():
    result = skill.validate_reply(
        json.dumps({"request_id": RID, "phase": "proposal", "error": "预算内凑不出完整一餐"}),
        request_id=RID,
    )
    assert result["error"] == "预算内凑不出完整一餐"
    assert "candidate_keys" not in result


@pytest.mark.parametrize("text", [
    "好的，我给你推荐番茄鸡蛋面。",                        # prose
    "",                                                    # empty
    "```\nnot json\n```",                                  # fenced non-JSON
    json.dumps([1, 2, 3]),                                 # array, not object
    _reply() + "\n另外还有别的建议",                        # trailing prose
    _reply() + "\n" + _reply(),                            # two objects
])
def test_rejects_non_contract_output(text):
    with pytest.raises(skill.SkillContractError):
        skill.validate_reply(text, request_id=RID)


@pytest.mark.parametrize("bad", [
    {"request_id": "22222222-2222-2222-2222-222222222222"},   # wrong request
    {"phase": "context"},                                     # wrong phase
    {"candidate_keys": []},                                   # empty keys
    {"candidate_keys": ["a"] * 7},                            # too many keys
    {"candidate_keys": ["a", "a"]},                           # duplicate keys
    {"candidate_keys": [123]},                                # wrong type
    {"reason": 123},                                          # wrong type
    {"reason": "长" * 201},                                   # too long
    {"context": {"meal_slot": "breakfast"}},                  # forbidden patch key
    {"context": "not-an-object"},                             # wrong patch type
    {"error": ""},                                            # empty error
    {"error": "长" * 301},                                    # error too long
    {"note": "extra"},                                        # unknown top-level key
])
def test_rejects_contract_violations(bad):
    with pytest.raises(skill.SkillContractError):
        skill.validate_reply(_reply(**bad), request_id=RID)


def test_prompt_carries_a_hard_data_boundary_and_the_task_id():
    prompt = skill.build_prompt(
        request_id=RID, instruction="清淡点",
        context={"meal_slot": "dinner"},
        candidates=[{"key": "recipe:101", "name": "番茄鸡蛋面"}],
    )
    assert skill.DATA_SEPARATOR in prompt
    # The only machine-readable payload is the LAST line, after the separator.
    payload = json.loads(prompt.splitlines()[-1])
    assert payload["request_id"] == RID
    assert payload["task_type"] == "fandecide_model_request"
    assert payload["candidates"][0]["key"] == "recipe:101"
    # The instruction lives INSIDE the data segment, so it is data, not a command.
    tail = prompt.split(skill.DATA_SEPARATOR)[1]
    assert "清淡点" in tail


def test_system_contract_forbids_actions_outside_the_product():
    for forbidden in ("下单", "扣库存", "读取凭据", "访问 URL"):
        assert forbidden in skill.SYSTEM_CONTRACT
    assert "JSON" in skill.SYSTEM_CONTRACT


# ---------------------------------------------------------------- error humanizing

POOL = [{"name": "番茄牛腩"}, {"name": "水煮牛肉"}]


@pytest.mark.parametrize("leak", [
    "用户指令要求'金汤牛肉'，但给定candidates列表中无任何菜品",
    "servings=2需家庭方案（complete+side或main+side+staple）",
    "只能从 candidate_keys 里挑真实 key，role 不匹配",
    "ProtectedAvoid 与 max_spice 冲突",
])
def test_internal_schema_words_never_reach_the_user(leak):
    out = skill.humanize_error(leak, POOL)
    for term in ("candidates", "servings", "complete", "main", "side", "staple",
                 "key", "role", "protected_avoid", "max_spice"):
        assert term not in out.lower()
    # The fallback names ONLY real pool dishes, never an invented one.
    assert "可以改成" in out and "番茄牛腩" in out


def test_an_invented_substitute_is_replaced_by_real_pool_dishes():
    leak = "金汤牛肉目前做不了，可以改成：西湖牛肉羹、小炒黄牛肉"
    out = skill.humanize_error(leak, POOL)
    assert "西湖牛肉羹" not in out, "an invented dish must not reach the user"
    assert "番茄牛腩" in out or "水煮牛肉" in out


def test_a_suggestion_naming_only_real_dishes_is_kept_verbatim():
    text = "金汤牛肉目前做不了，可以改成：番茄牛腩、水煮牛肉"
    assert skill.humanize_error(text, POOL) == text


def test_plain_user_language_is_not_rewritten():
    text = "这个要求暂时凑不出一份合适的方案"
    assert skill.humanize_error(text, POOL) == text


def test_empty_error_and_empty_pool_still_say_something_actionable():
    out = skill.humanize_error("", [])
    assert out and "可以改成" in out
    assert skill.humanize_error("candidates 不足", [])


# ---------------------------------------------------------------- 近似菜名匹配

BROCCOLI_POOL = [
    {"key": "recipe:291", "name": "蒜蓉西兰花"},
    {"key": "recipe:4", "name": "蒜蓉西蓝花"},
    {"key": "recipe:1", "name": "蚝油生菜"},
    {"key": "recipe:2", "name": "白灼菜心"},
]


@pytest.mark.parametrize("want,expected", [
    ("西蓝花", ["蒜蓉西兰花", "蒜蓉西蓝花"]),   # 异体字: ALIAS_PAIRS 归一
    ("西兰花", ["蒜蓉西兰花", "蒜蓉西蓝花"]),
    ("生菜", ["蚝油生菜"]),                    # 去烹饪手法后同核心名
    ("菜心", ["白灼菜心"]),
    ("金汤牛肉", []),                          # 池里确实没有
])
def test_match_candidates_finds_variant_writings(want, expected):
    assert [dish["name"] for dish in skill.match_candidates(want, BROCCOLI_POOL)] == expected


def test_a_single_shared_character_is_not_a_match():
    # 「菜」字在任何菜名里都有，不能因此把整池当成命中。
    assert skill.match_candidates("菜", BROCCOLI_POOL) == []


@pytest.mark.parametrize("instruction,names", [
    ("西蓝花", ["西蓝花"]),            # 整条消息就是一个菜名
    ("金汤牛肉", ["金汤牛肉"]),
    ("帮我做个番茄炒蛋", ["番茄炒蛋"]),
    ("想吃点暖胃的汤", []),            # 需求，不是菜名
    ("来点下饭的", []),
    ("两个人，不开火，不辣", []),        # 短句不是菜名
])
def test_named_wants_separates_dish_names_from_needs(instruction, names):
    assert skill.named_wants(instruction, BROCCOLI_POOL) == names


def test_named_is_never_need_only_when_a_pool_dish_matches():
    # 「西蓝花」在池里有等价菜 → 必须走严格路径去用它，而不是当需求去生成。
    assert skill.is_need_only("西蓝花", BROCCOLI_POOL) is False
    matched = [d["name"] for d in skill.resolve_named("西蓝花", BROCCOLI_POOL)]
    assert matched and all("西兰花" in name or "西蓝花" in name for name in matched)


def test_a_named_dish_missing_from_the_pool_yields_no_match():
    assert skill.resolve_named("金汤牛肉", BROCCOLI_POOL) == []
    # ... and that is what tells the orchestrator to generate substitutes.
    assert skill.named_wants("金汤牛肉", BROCCOLI_POOL) == ["金汤牛肉"]
