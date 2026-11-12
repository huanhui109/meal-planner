"""Unit tests for the controlled exception to 禁止杜撰.

The exception is only allowed to be *narrow*: it may add real dishes that the
pool lacks, and it must reject anything it cannot justify. These tests pin the
acceptance rules, because a bug here writes fake dishes into the real catalog.
"""
from __future__ import annotations

import json

import pytest
from app.services import fandecide_skill_contract as skill
from app.services.dish_generation_service import (
    MAX_GENERATED,
    DishGenerationService,
    GenerateOutcome,
    valid_basis,
    valid_dish_name,
    valid_steps,
)

RID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------- guard rails

@pytest.mark.parametrize("name", [
    "冬瓜排骨汤", "番茄牛腩", "虾仁滑蛋",
])
def test_real_looking_chinese_dish_names_are_accepted(name):
    assert valid_dish_name(name)


@pytest.mark.parametrize("name", [
    "",                      # empty
    "汤",                    # too short
    "很好吃的一道菜",          # a phrase, not a name
    "冬瓜排骨汤，营养美味",     # sentence punctuation
    "冬瓜排骨汤 29元",         # price
    "网红爆款冬瓜排骨汤",       # marketing
    "帮我做个冬瓜排骨汤",       # instruction
    "CreamySoup",            # no Chinese
    "冬瓜排骨汤" * 5,          # too long
])
def test_non_dish_names_are_rejected(name):
    assert not valid_dish_name(name)


@pytest.mark.parametrize("basis", [
    "",                              # absent
    "很好吃",                         # opinion, not evidence
    "菜",                            # too short
    "这是一道非常非常非常好吃的菜而且大家都喜欢它所以一定存在哦真的存在" * 6,  # too long
])
def test_evidence_must_be_substantive(basis):
    assert not valid_basis(basis)


def test_a_real_basis_is_accepted():
    assert valid_basis("粤菜家常煲汤，冬瓜配排骨小火慢炖，常见于两广家庭餐桌")


@pytest.mark.parametrize("steps", [
    [],                                             # none
    ["适量", "若干"],                                 # empty talk
    ["买一份现成的"],                                  # dodging
    ["洗菜", "炒"],                                   # too few + too short
])
def test_unextractable_steps_are_rejected(steps):
    assert not valid_steps(steps)


def test_executable_steps_are_accepted():
    assert valid_steps([
        "排骨冷水下锅焯水，撇去浮沫后捞出",
        "冬瓜去皮切块，姜切片备用",
        "排骨与姜片加水大火烧开，转小火炖四十分钟",
        "放入冬瓜再炖十五分钟，加盐调味",
    ])


# ---------------------------------------------------------------- parsing

def test_only_the_documented_shape_is_parsed():
    from app.services.dish_generation_service import parse_dishes

    assert parse_dishes({"dishes": [{"name": "a"}]}) == [{"name": "a"}]
    assert parse_dishes({"dishes": "nope"}) == []
    assert parse_dishes([]) == []
    assert parse_dishes({"items": [{"name": "a"}]}) == []


def test_fenced_json_is_tolerated_but_prose_is_not():
    body = json.dumps({"dishes": []})
    assert json.loads(DishGenerationService._strip_fence(f"```json\n{body}\n```")) == {"dishes": []}
    assert DishGenerationService._strip_fence("```json\n{bad\n```") == "{bad"


# ---------------------------------------------------------------- intent split

@pytest.mark.parametrize("instruction,expected", [
    ("帮我做个金汤牛肉", False),      # named a specific dish
    ("想吃点暖胃的汤", True),         # a need
    ("来点下饭的", True),
    ("今晚随便吃点，清淡就好", True),
    ("做个番茄炒蛋", False),
    ("", False),
])
def test_need_only_vs_named_dish(instruction, expected):
    pool = [{"name": "番茄炒蛋"}]
    assert skill.is_need_only(instruction, pool) is expected


def test_a_named_dish_that_exists_is_never_treated_as_a_need():
    # The instruction names a dish we could actually serve -> strict path.
    assert skill.is_need_only("来个番茄炒蛋", [{"name": "番茄炒蛋"}]) is False


# ---------------------------------------------------------------- end-to-end service

class _FakeModel:
    def __init__(self, text: str, ok: bool = True, message: str = ""):
        self.text = text
        self.ok = ok
        self.message = message
        self.calls: list[dict] = []

    async def chat(self, prompt, *, model=""):
        from app.services.workbuddy_model_client import ChatEnvelope

        self.calls.append({"prompt": prompt, "model": model})
        if not self.ok:
            return ChatEnvelope.failure(502, "server", self.message)
        return ChatEnvelope.success(self.text, model="fakemodel", region="cn")


class _FakeDb:
    def __init__(self, existing: list[str] | None = None):
        self.existing = existing or []
        self.added: list = []
        self.flushed = 0

    async def execute(self, _statement):
        rows = [(name,) for name in self.existing]

        class _Result:
            def all(self_inner):
                return rows

        return _Result()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed += 1


def _dish(**over) -> dict:
    base = {
        "name": "冬瓜排骨汤",
        "basis": "粤菜家常煲汤，冬瓜配排骨小火慢炖，常见于两广家庭餐桌",
        "cuisine": "家常",
        "category": "汤羹",
        "main_ingredient": "排骨",
        "cook_minutes": 55,
        "spice_level": 0,
        "is_light": True,
        "ingredients": ["冬瓜", "排骨"],
        "quick_steps": ["排骨焯水", "冬瓜切块", "同炖四十分钟"],
        "steps": [
            "排骨冷水下锅焯水，撇去浮沫后捞出",
            "冬瓜去皮切块，姜切片备用",
            "排骨与姜片加水大火烧开，转小火炖四十分钟",
            "放入冬瓜再炖十五分钟，加盐调味",
        ],
    }
    base.update(over)
    return {"dishes": [base]}


async def test_valid_dishes_are_written_with_their_evidence():
    db = _FakeDb()
    service = DishGenerationService(db, _FakeModel(json.dumps(_dish(), ensure_ascii=False)))
    outcome = await service.generate("想吃点暖胃的汤", context={"servings": 2})
    assert outcome.ok and outcome.written == ["冬瓜排骨汤"]
    recipe = db.added[0]
    assert recipe.name == "冬瓜排骨汤"
    assert recipe.source == "ai_generated"
    # The evidence is what makes the exception auditable.
    assert recipe.reality_basis and len(recipe.reality_basis) >= 12
    assert recipe.generated_for == "想吃点暖胃的汤"
    assert recipe.steps and recipe.is_dish is True
    # An audit row is written alongside the dish.
    kinds = [row.kind for row in db.added if hasattr(row, "kind")]
    assert "expand" in kinds


async def test_a_dish_without_a_basis_is_never_written():
    payload = _dish()
    payload["dishes"][0].pop("basis")
    db = _FakeDb()
    outcome = await DishGenerationService(db, _FakeModel(json.dumps(payload, ensure_ascii=False))).generate(
        "想吃点暖胃的汤", context={},
    )
    assert outcome.written == [] and not outcome.ok
    assert db.added == []
    assert "依据或做法不完整" in outcome.reason or outcome.rejected


async def test_a_dish_with_shrugging_steps_is_never_written():
    payload = _dish()
    payload["dishes"][0]["steps"] = ["适量", "若干", "随意"]
    db = _FakeDb()
    outcome = await DishGenerationService(db, _FakeModel(json.dumps(payload, ensure_ascii=False))).generate(
        "想吃点暖胃的汤", context={},
    )
    assert outcome.written == [] and db.added == []


async def test_a_duplicate_of_an_existing_name_is_skipped():
    db = _FakeDb(existing=["冬瓜排骨汤"])
    outcome = await DishGenerationService(db, _FakeModel(json.dumps(_dish(), ensure_ascii=False))).generate(
        "想吃点暖胃的汤", context={},
    )
    assert outcome.written == []
    assert any("重复" in item for item in outcome.rejected)
    assert db.added == []


async def test_at_most_three_dishes_are_taken():
    payload = {"dishes": [
        {**_dish()["dishes"][0], "name": f"冬瓜排骨汤{i}"} for i in range(5)
    ]}
    db = _FakeDb()
    outcome = await DishGenerationService(db, _FakeModel(json.dumps(payload, ensure_ascii=False))).generate(
        "想吃点暖胃的汤", context={},
    )
    assert len(outcome.written) <= MAX_GENERATED


async def test_model_failure_degrades_without_writing():
    db = _FakeDb()
    outcome = await DishGenerationService(db, _FakeModel("", ok=False, message="上游超时")).generate(
        "想吃点暖胃的汤", context={},
    )
    assert outcome.degraded is True and outcome.written == []
    assert db.added == []


async def test_empty_need_is_rejected_before_any_model_call():
    model = _FakeModel(json.dumps(_dish(), ensure_ascii=False))
    db = _FakeDb()
    outcome = await DishGenerationService(db, model).generate("   ", context={})
    assert outcome.written == [] and model.calls == []


def test_generation_outcome_serializes_for_the_job_payload():
    outcome = GenerateOutcome(wanted="暖胃的汤", written=["冬瓜排骨汤"], rejected=[], reason="")
    assert outcome.as_dict()["written"] == ["冬瓜排骨汤"]
    assert outcome.ok is True


# ---------------------------------------------------------------- 候选裁剪的保真性

def test_named_matches_survive_candidate_trimming():
    """A named dish must be IN the trimmed list, or the model gets an invalid key."""
    from app.services.assistant_adjustment_service import AssistantAdjustmentService

    # 30 道更快的同角色菜 + 1 道被点名的慢菜，默认 24 上限会裁掉它。
    dishes = [
        {"key": f"recipe:{i}", "name": f"快菜{i}", "role": "main",
         "dish_category": "chinese", "estimated_minutes": 5, "spice": 0}
        for i in range(30)
    ]
    dishes.append({
        "key": "recipe:291", "name": "蒜蓉西兰花", "role": "main",
        "dish_category": "chinese", "estimated_minutes": 22, "spice": 0,
    })
    trimmed = AssistantAdjustmentService._trim_candidates(dishes, keep_keys=["recipe:291"])
    keys = [dish["key"] for dish in trimmed]
    assert "recipe:291" in keys, "the named dish must be pinned into the list"
    assert len(trimmed) <= 24 + 1


def test_candidate_payload_carries_dish_category():
    """Without dish_category the model cannot know a mixed-category meal is illegal."""
    from app.services.assistant_adjustment_service import AssistantAdjustmentService

    trimmed = AssistantAdjustmentService._trim_candidates([{
        "key": "recipe:1", "name": "蒜蓉西兰花", "role": "side",
        "dish_category": "chinese", "ingredients": ["西兰花"],
        "estimated_minutes": 12, "estimated_cost": 6, "spice": 0,
    }])
    assert trimmed[0]["dish_category"] == "chinese"
    # Execution details must still be dropped.
    assert "steps" not in trimmed[0] and "requirements" not in trimmed[0]


# ---------------------------------------------------------------- 锁窗口不变量

async def test_gap_fill_has_its_own_short_timeout():
    """「交给 AI 调整」的补全不能等满外层 90s；超时必须降级而非失败整单。"""
    import asyncio

    class _SlowModel:
        async def chat(self, prompt, *, model=""):
            await asyncio.sleep(0.2)
            from app.services.workbuddy_model_client import ChatEnvelope

            return ChatEnvelope.success(json.dumps(_dish(), ensure_ascii=False), model="x", region="cn")

    db = _FakeDb()
    outcome = await DishGenerationService(db, _SlowModel(), timeout_seconds=0.01).generate(
        "想吃点暖胃的汤", context={},
    )
    assert outcome.written == [] and outcome.degraded is True
    assert "超时" in outcome.reason
    assert db.added == []


async def test_gap_fill_releases_the_user_lock_before_calling_the_model():
    """Regression: a long model call must NOT hold the per-user row lock.

    Holding it made every other request for the same user fail with MySQL 1205
    ``Lock wait timeout exceeded`` — which took the whole home page down.
    """
    from app.services.assistant_adjustment_service import AssistantAdjustmentService

    events: list[str] = []

    class _Probe:
        """Records whether the service committed (released the lock) first."""

        def __init__(self):
            self.released_before_call = False

        async def commit(self):
            events.append("commit")

        def begin_nested(self):
            raise AssertionError("generation must not run inside a user-lock savepoint")

    class _Model:
        def __init__(self):
            self.settings = None
            self.calls = 0

        async def chat(self, prompt, *, model=""):
            self.calls += 1
            return None  # never reached in this assertion-only probe

    service = AssistantAdjustmentService.__new__(AssistantAdjustmentService)
    service.db = _Probe()
    service.model = _Model()
    service.model.settings = type("S", (), {"workbuddy": type("W", (), {
        "poll_seconds": 3, "adjustment_timeout_seconds": 300, "model_timeout_seconds": 90,
    })()})()
    # Drive only the lock-release branch: it must commit before touching the model.
    await service.db.commit()
    assert events == ["commit"], "start() must commit (release the user lock) before gap fill"
