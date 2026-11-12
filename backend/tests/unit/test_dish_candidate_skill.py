"""Contract tests for the in-app 候选菜品 skill (fandecide-candidates).

Two jobs here:

1. Pin the SPEC: trigger/input/output/count/latency wording in SKILL.md and
   contract.json must agree with the executable constants in Python. Doc drift is
   exactly how "默认 4 个" turns into "代码补 3 道".
2. Reverse-verify the guard rails: inject known violations (fake dish names,
   missing evidence, shrug steps, prose replies, extra keys) and assert they are
   REJECTED. A validator that always returns empty would otherwise look safe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services import dish_candidate_skill as skill

ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / "skills" / "fandecide-candidates"

BASIS = "粤菜家常煲汤，冬瓜配排骨小火慢炖，常见于两广家庭餐桌"
STEPS = [
    "排骨冷水下锅焯水，撇去浮沫后捞出",
    "冬瓜去皮切块，姜切片备用",
    "排骨与姜片加水大火烧开，转小火炖四十分钟",
    "放入冬瓜再炖十五分钟，加盐调味",
]


def _candidate(name: str = "冬瓜排骨汤", **over) -> dict:
    base = {
        "name": name,
        "cuisine": "家常",
        "category": "汤羹",
        "main_ingredient": "排骨",
        "cook_minutes": 55,
        "spice_level": 0,
        "is_light": True,
        "ingredients": ["冬瓜", "排骨", "姜"],
        "quick_steps": ["排骨焯水", "冬瓜切块", "小火同炖"],
        "steps": list(STEPS),
        "reality_basis": BASIS,
    }
    base.update(over)
    return base


def _reply(*items: dict) -> str:
    return json.dumps({"candidates": list(items)}, ensure_ascii=False)


# ---------------------------------------------------------------- spec is the truth

def test_skill_spec_and_json_contract_agree_with_python_constants():
    schema = json.loads((SKILL_DIR / "contract.json").read_text(encoding="utf-8"))
    node = schema["definitions"]["candidate"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"candidates"}
    assert schema["properties"]["candidates"]["minItems"] == skill.MIN_COUNT == 3
    assert schema["properties"]["candidates"]["maxItems"] == skill.MAX_COUNT == 5
    assert set(node["required"]) == set(skill.CANDIDATE_FIELDS)
    assert node["additionalProperties"] is False
    assert skill.DEFAULT_COUNT == 4

    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for section in ("触发条件", "输入内容", "输出字段", "默认候选数量", "运行约束（低延迟优先）"):
        assert section in text, f"SKILL.md 缺规格章节：{section}"
    assert "默认 4 个" in text and "3–5" in text
    assert "不追问" in text and "不展开" in text and "单次请求" in text


def test_normalize_count_clamps_out_of_range_and_bad_types():
    assert skill.normalize_count(None) == 4
    assert skill.normalize_count("4") == 4
    assert skill.normalize_count(True) == 4
    assert skill.normalize_count(1) == 3
    assert skill.normalize_count(99) == 5
    assert skill.normalize_count(4) == 4


def test_system_contract_forbids_questions_analysis_and_invention():
    text = skill.SYSTEM_CONTRACT
    assert "不追问" in text and "绝不展开分析" in text
    assert "不得自创" in text and "唯一输出是一个 JSON 对象" in text
    assert "不得声称具备" in text


# ---------------------------------------------------------------- prompt

def test_prompt_is_single_turn_short_and_data_only():
    prompt = skill.build_prompt("想吃点暖胃的汤", context={"servings": 2}, count=3)
    lines = prompt.splitlines()
    assert lines[0].startswith(skill.PROMPT_LEAD)
    assert skill.DATA_SEPARATOR in lines
    data = json.loads(lines[-1])
    assert data["task_type"] == skill.TASK_TYPE
    assert data["description"] == "想吃点暖胃的汤"
    assert data["count"] == 3
    assert data["context"] == {"servings": 2}
    assert "不追问" in prompt and "不分析" in prompt
    # No multi-turn / deep-reasoning framing, and no full recipe library.
    assert "多轮" not in prompt and "请详细分析" not in prompt


def test_prompt_carries_named_dish_and_exclude_names():
    prompt = skill.build_prompt("想吃西蓝花", exclude_names=["蒜蓉西兰花"], named_dish="西蓝花")
    data = json.loads(prompt.splitlines()[-1])
    assert data["named_dish"] == "西蓝花"
    assert data["exclude_names"] == ["蒜蓉西兰花"]
    assert "西蓝花" in prompt.splitlines()[0]


def test_prompt_truncates_description_and_excludes():
    prompt = skill.build_prompt("暖" * 500, exclude_names=[f"菜{i}" for i in range(500)])
    data = json.loads(prompt.splitlines()[-1])
    assert len(data["description"]) == skill.MAX_DESCRIPTION
    assert len(data["exclude_names"]) == skill.MAX_EXCLUDE_NAMES


# ---------------------------------------------------------------- strict parsing

def test_canonical_reply_returns_fixed_structure():
    dishes = skill.parse_reply(_reply(*[_candidate(f"冬瓜排骨汤{i}") for i in range(4)]), count=4)
    assert len(dishes) == 4
    for dish in dishes:
        assert set(dish.as_dict()) == set(skill.CANDIDATE_FIELDS)
        assert dish.as_dict()["reality_basis"] == BASIS
        assert dish.as_dict()["steps"] == STEPS
    kwargs = dishes[0].to_recipe_kwargs("想吃点暖胃的汤")
    assert kwargs["name"] == "冬瓜排骨汤0"
    assert kwargs["reality_basis"] == BASIS
    assert kwargs["generated_for"] == "想吃点暖胃的汤"
    assert kwargs["source"] == "ai_generated" and kwargs["is_dish"] is True
    assert "ingredients" not in kwargs, "recipe 表没有 ingredients 列"
    assert len(kwargs["generated_for"]) <= skill.WANT_MAX


@pytest.mark.parametrize("text", [
    "我觉得可以试试番茄炒蛋，暖胃又下饭",                       # prose
    '{"candidates":[]} {"candidates":[]}',                    # two objects
    '{"candidates":[]} 补充说明',                              # trailing text
    '{"candidates":[], "reason":"因为好吃"}',                   # extra top-level key
    '{"items":[]}',                                            # wrong key
    '{"candidates":"四道菜"}',                                 # not an array
    "",                                                        # empty
    "```json\n{bad\n```",                                      # broken JSON
    "x" * (skill.MAX_REPLY + 1),                               # too long
])
def test_malformed_replies_are_rejected(text):
    with pytest.raises(skill.CandidateSkillError):
        skill.parse_reply(text)


def test_invented_or_unjustified_dishes_are_dropped_not_repaired():
    """Reverse verification: known violations must NOT sneak into the pool."""
    text = _reply(
        _candidate("清炖冬瓜汤"),
        _candidate("网红爆款养生汤"),                    # marketing name
        _candidate("番茄牛腩", reality_basis="很好吃"),  # no evidence
        _candidate("紫菜蛋花汤", steps=["适量", "若干", "随意"]),
        _candidate("清炖冬瓜汤"),                       # duplicate
        _candidate("萝卜排骨汤", reality_basis=""),     # absent evidence
    )
    dishes = skill.parse_reply(text, count=5)
    # 营销名 / 无依据 / 空话步骤 / 重复 / 缺依据全部丢弃，只有证据齐全的一道留下。
    assert [dish.name for dish in dishes] == ["清炖冬瓜汤"]


def test_reply_is_capped_at_requested_count():
    text = _reply(*[_candidate(f"家常小炒{i}") for i in range(6)])
    assert len(skill.parse_reply(text, count=3)) == 3
    assert len(skill.parse_reply(text, count=5)) == 5


def test_legacy_aliases_still_parse_under_the_same_rules():
    legacy = {"dishes": [{**_candidate(), "basis": BASIS}]}
    legacy["dishes"][0].pop("reality_basis")
    dishes = skill.parse_reply(json.dumps(legacy, ensure_ascii=False))
    assert len(dishes) == 1 and dishes[0].basis == BASIS
