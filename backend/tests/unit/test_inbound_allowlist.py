"""T05：事件白名单注册表单测 —— 默认拒绝与永久禁止清单。

服务端 ``AllowlistRegistry`` 独立硬编码枚举，绝不 import 前端 TS；本测试用**读取
shared/inboundBridge.ts 文本**的方式核对版本常量同值，不引入任何跨语言运行时依赖。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.services.inbound_bridge import (
    ALLOWLIST_VERSION,
    ERR_ALLOWLIST,
    AllowlistRegistry,
    BridgeReject,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = AllowlistRegistry()

P0_EVENTS = (
    ("meal.adjust.requested", "web_to_bridge", "-"),
    ("meal.adjust.cancelled", "web_to_bridge", "-"),
    ("meal.adjust.status_queried", "web_to_bridge", "-"),
    ("assistant.context_replied", "assistant_to_bridge", "context"),
    ("assistant.proposal_replied", "assistant_to_bridge", "proposal"),
    ("assistant.failed", "assistant_to_bridge", "context"),
    ("assistant.failed", "assistant_to_bridge", "proposal"),  # 失败允许两个阶段
)
P1_DISABLED = (
    "pair.status_queried",
    "pair.connection_managed",
    "task.status_queried",
)


def _reject(event_type, direction="web_to_bridge", phase="-", version=ALLOWLIST_VERSION):
    """调用 check 并返回抛出的 BridgeReject，未抛则说明放行了禁止事件。"""
    with pytest.raises(BridgeReject) as exc:
        REGISTRY.check(event_type, direction, phase, version)
    assert exc.value.status == 403
    assert exc.value.code == ERR_ALLOWLIST
    return exc.value


def test_version_is_ib_1_0_and_matches_shared_ts():
    """后端 ALLOWLIST_VERSION 与 shared/inboundBridge.ts 的 INBOUND_ALLOWLIST_VERSION 同值。"""
    assert ALLOWLIST_VERSION == "ib-1.0"
    assert REGISTRY.VERSION == "ib-1.0"
    shared = (REPO_ROOT / "shared" / "inboundBridge.ts").read_text(encoding="utf-8")
    match = re.search(r"INBOUND_ALLOWLIST_VERSION\s*=\s*'([^']+)'", shared)
    assert match is not None, "shared/inboundBridge.ts 缺少 INBOUND_ALLOWLIST_VERSION"
    assert match.group(1) == ALLOWLIST_VERSION


def test_p0_six_events_pass():
    """P0 六类（含 assistant.failed 两阶段）通过并返回 event_type。"""
    for event_type, direction, phase in P0_EVENTS:
        assert REGISTRY.check(event_type, direction, phase, ALLOWLIST_VERSION) == event_type


def test_p1_three_events_are_registered_but_disabled():
    """P1 三类登记枚举但 disabled，一律默认拒绝。"""
    for event_type in P1_DISABLED:
        rej = _reject(event_type, "web_to_bridge", "-", ALLOWLIST_VERSION)
        assert rej.reason_code == "not_allowlisted"


def test_unlisted_event_is_denied_by_default():
    """未登记事件默认拒绝，不降级成 prompt 指令。"""
    rej = _reject("totally.unknown.event")
    assert rej.reason_code == "not_allowlisted"


def test_direction_and_phase_mismatch_are_denied():
    """方向与阶段不匹配拒绝。"""
    rej = _reject("meal.adjust.requested", direction="assistant_to_bridge", phase="-")
    assert rej.reason_code == "direction_mismatch"
    rej = _reject("assistant.context_replied", direction="assistant_to_bridge", phase="proposal")
    assert rej.reason_code == "phase_mismatch"
    rej = _reject("assistant.context_replied", direction="assistant_to_bridge", phase="-")
    assert rej.reason_code == "phase_mismatch"


def test_version_mismatch_is_denied():
    """版本不匹配拒绝（含完全合法的 P0 事件）。"""
    rej = _reject("meal.adjust.requested", version="ib-0.9")
    assert rej.reason_code == "version_mismatch"
    rej = _reject("meal.adjust.requested", version="ib-2.0")
    assert rej.reason_code == "version_mismatch"


def test_frozen_forbidden_has_16_entries_and_none_can_pass():
    """永久禁止清单 16 条，含通配符 order.* / payment.*，无一可通过。"""
    forbidden = REGISTRY.FROZEN_FORBIDDEN
    assert len(forbidden) == 16
    assert "order.*" in forbidden and "payment.*" in forbidden

    for pattern in sorted(forbidden):
        rej = _reject(pattern, "web_to_bridge", "-", ALLOWLIST_VERSION)
        assert rej.reason_code == "forbidden", pattern

    # 通配符必须能挡住具体展开的事件名，而不只是挡住字面量 "order.*"
    for wildcard_event in ("order.create", "order.submit", "order.cancel", "payment.pay", "payment.refund"):
        rej = _reject(wildcard_event, "web_to_bridge", "-", ALLOWLIST_VERSION)
        assert rej.reason_code == "forbidden", wildcard_event

    # 禁止清单优先级最高：即使版本也不对，仍按 forbidden 拒绝
    rej = _reject("meal.accept", version="ib-0.9")
    assert rej.reason_code == "forbidden"


def test_enumerate_is_complete_and_fields_are_present():
    """enumerate() 可枚举 9 项，六 enabled / 三 disabled，字段齐全。"""
    rows = REGISTRY.enumerate()
    assert isinstance(rows, list) and len(rows) == 9
    assert {row["event_type"] for row in rows} == set(REGISTRY.ALLOWED_EVENTS)
    assert sum(1 for row in rows if row["enabled"]) == 6
    assert sum(1 for row in rows if not row["enabled"]) == 3
    for row in rows:
        assert set(row) == {"event_type", "enabled", "directions", "phases", "version"}
        assert row["version"] == "ib-1.0"
        assert isinstance(row["directions"], list) and row["directions"]
        assert isinstance(row["phases"], list) and row["phases"]
    assert {row["event_type"] for row in rows if not row["enabled"]} == set(P1_DISABLED)
