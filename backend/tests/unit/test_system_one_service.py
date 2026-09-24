"""System One 接入层单测

硬约束: 这批用例**不得依赖网络、API Key 或模型权重**。CI 断网、机器上没装 torch
时必须全绿 —— 决策模型是加分项而不是依赖项, 测试要是依赖它, 就等于把它变成了依赖项。

所以这里只验证: 归一化、问题构造、降级、缓存, 以及 Laya 本地调用的正确接线
(用假的 agent 替身, 不真加载 421M 权重)。
"""

from __future__ import annotations

import json

import pytest
from app.config import SystemOneSettings
from app.services import system_one_service as sos
from app.services.system_one_service import (
    EMPTY,
    ChoiceAnswer,
    ChoiceQ,
    NoulAnswer,
    NoulQ,
    ScoreAnswer,
    ScoreQ,
    SystemOneResult,
    SystemOneService,
    _build_questions,
    _laya_raw_questions,
    _normalize,
)


class _FakeAnswer:
    """模拟 pydantic 风格的答案对象(typesafe_sdk / system-one-adapter 用这形状)"""

    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


def _settings(**kw) -> SystemOneSettings:
    base = {"enabled": True}
    base.update(kw)
    return SystemOneSettings(**base)


# ------------------------------------------------------------------ 归一化

def test_normalize_choice_from_object():
    raw = {"dept": _FakeAnswer("choice", choice="billing", confidence=0.91,
                               probabilities={"billing": 0.9, "tech": 0.1})}
    res = _normalize(raw, "jev")
    assert res.ok and res.provider == "jev"
    assert res.choice("dept") == "billing"
    assert res.confidence("dept") == pytest.approx(0.91)
    assert res.noul("dept") == 0.5  # 类型不匹配, 回落默认值而不是报错


def test_normalize_laya_dict_answers():
    """Laya 返回的是纯 dict(不是 pydantic 对象), 必须也能归一化"""
    raw = {
        "intent": {"type": "choice", "choice": "describe_taste", "confidence": 0.87,
                   "probabilities": {"describe_taste": 0.87, "other": 0.13}},
        "urgency": {"type": "score", "score": 1.4, "confidence": 0.8,
                    "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}},
        "is_light": {"type": "noul", "noul": 0.97, "confidence": 0.97},
    }
    res = _normalize(raw, "laya")
    assert res.ok and res.provider == "laya"
    assert res.choice("intent") == "describe_taste"
    assert res.score("urgency") == pytest.approx(1.4)
    assert res.noul("is_light") == pytest.approx(0.97)
    # Laya 的 Noul 带 confidence(max(p, 1-p)), Jev 没有 —— 这里要能取到
    assert res.confidence("is_light") == pytest.approx(0.97)


def test_normalize_skips_unknown_type():
    assert not _normalize({"x": {"type": "whatever"}}, "laya").ok


def test_normalize_tolerates_missing_fields():
    """字段缺失/类型异常不能炸 —— 上游换版本时宁可丢一条判断也不能 500"""
    res = _normalize({"a": {"type": "choice"}}, "laya")
    assert res.choice("a") is None
    assert res.confidence("a") == 0.0


def test_answer_defaults_are_safe():
    assert ChoiceAnswer().choice is None and ChoiceAnswer().confidence == 0.0
    assert NoulAnswer().noul == 0.5 and NoulAnswer().confidence == 0.0
    assert ScoreAnswer().score == 0.0


# ------------------------------------------------------------------ 问题构造

def test_laya_raw_questions_uses_plain_dicts():
    """Laya 不需要 SDK 的问题类, 直接用原生 dict"""
    raw = _laya_raw_questions({
        "a": ChoiceQ("选哪个", {"x": "含义X", "y": "含义Y"}),
        "b": ScoreQ("多严重", ["低", "中", "高"]),
        "c": NoulQ("是不是"),
    })
    assert raw["a"] == {"type": "choice", "instructions": "选哪个",
                        "criteria": {"x": "含义X", "y": "含义Y"}}
    assert raw["b"]["type"] == "score" and raw["b"]["criteria"] == ["低", "中", "高"]
    assert raw["c"]["type"] == "noul" and "criteria" not in raw["c"]


def test_laya_raw_questions_rejects_unknown():
    with pytest.raises(TypeError):
        _laya_raw_questions({"a": object()})


def test_build_questions_maps_all_primitives():
    from typesafe_sdk import Choice, Noul, Score

    built = _build_questions(
        {"a": ChoiceQ("选哪个", {"x": "含义X"}), "b": ScoreQ("多严重", ["低", "中"]),
         "c": NoulQ("是不是")},
        Choice, Score, Noul,
    )
    assert built["a"].type == "choice" and built["b"].type == "score" and built["c"].type == "noul"


# ------------------------------------------------------------------ 降级

@pytest.mark.asyncio
async def test_disabled_returns_empty():
    svc = SystemOneService(_settings(enabled=False, provider="laya"))
    assert await svc.evaluate("随便", {"a": NoulQ("是不是")}) is EMPTY


@pytest.mark.asyncio
async def test_rule_provider_never_calls_out():
    svc = SystemOneService(_settings(provider="rule"))
    res = await svc.evaluate("随便", {"a": NoulQ("是不是")})
    assert not res.ok and res.provider == "none"


@pytest.mark.asyncio
async def test_jev_without_key_is_not_usable():
    svc = SystemOneService(_settings(provider="jev", api_key=""))
    assert not svc.usable
    assert not (await svc.evaluate("随便", {"a": NoulQ("是不是")})).ok


@pytest.mark.asyncio
async def test_laya_failure_degrades_silently(monkeypatch):
    """权重加载失败/推理报错都必须静默降级, 绝不抛出"""

    def boom(*a, **kw):
        raise RuntimeError("no weights")

    monkeypatch.setattr(sos, "_laya_agent", boom)
    svc = SystemOneService(_settings(provider="laya"))
    res = await svc.evaluate("随便", {"a": NoulQ("是不是")})
    assert not res.ok and res.degraded and "no weights" in res.error
    assert svc.last_error == "no weights"


@pytest.mark.asyncio
async def test_unknown_provider_returns_empty():
    svc = SystemOneService(_settings(provider="nope"))
    assert not (await svc.evaluate("随便", {"a": NoulQ("是不是")})).ok


# ------------------------------------------------------------------ Laya 接线

class _FakeAgent:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        return self.payload


@pytest.mark.asyncio
async def test_laya_predict_wiring(monkeypatch):
    """验证传给 Laya 的问题形状与返回的归一化结果 —— 不真加载权重"""
    payload = {"answers": {
        "is_light": {"type": "noul", "noul": 0.93, "confidence": 0.93},
        "cuisine": {"type": "choice", "choice": "粤菜", "confidence": 0.71,
                    "probabilities": {"粤菜": 0.71, "家常": 0.29}},
    }}
    fake = _FakeAgent(payload)
    monkeypatch.setattr(sos, "_laya_agent", lambda *a, **kw: fake)

    svc = SystemOneService(_settings(provider="laya", laya_checkpoint="multilingual"))
    res = await svc.evaluate("想吃清淡的粤菜", {"is_light": NoulQ("想吃清淡的"),
                                                "cuisine": ChoiceQ("哪个菜系", {"粤菜": "清淡"})})
    assert res.ok and res.provider == "laya"
    assert res.noul("is_light") == pytest.approx(0.93)
    assert res.choice("cuisine") == "粤菜"

    state, questions = fake.calls[0]
    assert state == "想吃清淡的粤菜"
    assert questions["is_light"] == {"type": "noul", "instructions": "想吃清淡的"}
    assert questions["cuisine"]["criteria"] == {"粤菜": "清淡"}


@pytest.mark.asyncio
async def test_laya_auto_checkpoint_uses_router(monkeypatch):
    """checkpoint=auto 时应该走 Router 自动按语种分发"""
    payload = {"answers": {"is_light": {"type": "noul", "noul": 0.88, "confidence": 0.88}}}
    fake = _FakeAgent(payload)
    monkeypatch.setattr(sos, "_laya_router", lambda *a, **kw: fake)
    svc = SystemOneService(_settings(provider="laya", laya_checkpoint="auto"))
    res = await svc.evaluate("清淡点", {"is_light": NoulQ("想吃清淡的")})
    assert res.ok and res.noul("is_light") == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_laya_runs_off_the_event_loop(monkeypatch):
    """Laya 是同步推理, 必须丢到线程里跑, 否则会阻塞整个事件循环"""
    import threading

    main_thread = threading.current_thread()

    class _Blocking(_FakeAgent):
        def predict(self, state, questions):
            assert threading.current_thread() is not main_thread
            return self.payload

    monkeypatch.setattr(
        sos, "_laya_agent",
        lambda *a, **kw: _Blocking({"answers": {"a": {"type": "noul", "noul": 0.9}}}),
    )
    svc = SystemOneService(_settings(provider="laya"))
    res = await svc.evaluate("随便", {"a": NoulQ("是不是")})
    assert res.ok


# ------------------------------------------------------------------ 缓存

@pytest.mark.asyncio
async def test_cache_hits_within_ttl():
    calls = {"n": 0}

    async def fake(*a, **kw):
        calls["n"] += 1
        return _normalize({"a": {"type": "noul", "noul": 0.9}}, "jev")

    svc = SystemOneService(_settings(provider="jev", api_key="k", cache_seconds=60))
    svc._call_jev = fake  # type: ignore[assignment]
    qs = {"a": NoulQ("是不是")}

    await svc.evaluate("同一句话", qs)
    await svc.evaluate("同一句话", qs)
    assert calls["n"] == 1, "同样的问题不该打第二次模型"

    await svc.evaluate("另一句话", qs)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cache_key_differs_by_checkpoint():
    """换 checkpoint 必须换缓存 key, 否则 multilingual 的结果会被 english 命中"""
    svc1 = SystemOneService(_settings(provider="laya", laya_checkpoint="multilingual"))
    svc2 = SystemOneService(_settings(provider="laya", laya_checkpoint="english"))
    qs = {"a": NoulQ("是不是")}
    assert svc1._cache_key("同一句话", qs) != svc2._cache_key("同一句话", qs)


def test_as_dict_is_serializable():
    res = SystemOneResult(provider="laya", ok=True,
                          answers={"a": ChoiceAnswer(choice="x", confidence=0.9,
                                                     probabilities={"x": 0.9})})
    json.dumps(res.as_dict(), ensure_ascii=False)
