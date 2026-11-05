"""事件白名单注册表 - 服务端独立硬编码。

绝不 import shared/inboundBridge.ts, 也绝不读配置来放开禁止清单: 前端传来的枚举值
永远不被信任。默认拒绝: 不在枚举 / enabled=false / 方向或阶段不匹配 / 版本不匹配 /
命中 FROZEN_FORBIDDEN, 一律 403。
"""
from __future__ import annotations

import fnmatch

from . import ALLOWLIST_VERSION, DIRECTIONS, ERR_ALLOWLIST, PHASES, BridgeReject

_REJECT_MSG = "本次操作不在允许范围内，已拒绝"


class AllowlistRegistry:
    """白名单 + 永久禁止清单 + 版本。"""

    VERSION = ALLOWLIST_VERSION

    # P0 六类 enabled, P1 三类登记但 disabled。assistant.failed 允许 context 与 proposal
    # 两个阶段 (失败可发生在任一阶段)。
    ALLOWED_EVENTS: dict[str, dict] = {
        "meal.adjust.requested": {"enabled": True, "directions": ("web_to_bridge",), "phases": ("-",)},
        "meal.adjust.cancelled": {"enabled": True, "directions": ("web_to_bridge",), "phases": ("-",)},
        "meal.adjust.status_queried": {"enabled": True, "directions": ("web_to_bridge",), "phases": ("-",)},
        "assistant.context_replied": {
            "enabled": True, "directions": ("assistant_to_bridge",), "phases": ("context",),
        },
        "assistant.proposal_replied": {
            "enabled": True, "directions": ("assistant_to_bridge",), "phases": ("proposal",),
        },
        "assistant.failed": {
            "enabled": True, "directions": ("assistant_to_bridge",), "phases": ("context", "proposal"),
        },
        "pair.status_queried": {"enabled": False, "directions": ("web_to_bridge",), "phases": ("-",)},
        "pair.connection_managed": {"enabled": False, "directions": ("web_to_bridge",), "phases": ("-",)},
        "task.status_queried": {"enabled": False, "directions": ("web_to_bridge",), "phases": ("-",)},
    }

    # 永久禁止清单。硬编码 frozenset, 不提供任何配置键, 收紧/放开白名单都不影响它。
    FROZEN_FORBIDDEN: frozenset[str] = frozenset({
        "order.*",
        "payment.*",
        "meal.accept",
        "meal.complete",
        "meal.undo",
        "inventory.deduct",
        "message.send_external",
        "preference.write",
        "restriction.write",
        "tool.execute",
        "cli.execute",
        "url.fetch_arbitrary",
        "credential.read",
        "conversation.read_other",
        "approval.answer_on_behalf",
        "event.unlisted",
    })

    DIRECTIONS = DIRECTIONS
    PHASES = PHASES

    def check(self, event_type: str, direction: str, phase: str, version: str) -> str:
        """默认拒绝四级校验。通过返回 event_type, 不通过抛 BridgeReject(403, 1403, reason)。"""
        for pattern in self.FROZEN_FORBIDDEN:
            if event_type == pattern or fnmatch.fnmatchcase(event_type, pattern):
                raise BridgeReject(403, ERR_ALLOWLIST, "forbidden", _REJECT_MSG)
        if version != self.VERSION:
            raise BridgeReject(403, ERR_ALLOWLIST, "version_mismatch", _REJECT_MSG)
        policy = self.ALLOWED_EVENTS.get(event_type)
        if policy is None or not policy["enabled"]:
            raise BridgeReject(403, ERR_ALLOWLIST, "not_allowlisted", _REJECT_MSG)
        if direction not in policy["directions"]:
            raise BridgeReject(403, ERR_ALLOWLIST, "direction_mismatch", _REJECT_MSG)
        if phase not in policy["phases"]:
            raise BridgeReject(403, ERR_ALLOWLIST, "phase_mismatch", _REJECT_MSG)
        return event_type

    def enumerate(self) -> list[dict]:
        """可枚举列表: 每项含 event_type / enabled / directions / phases / version。"""
        return [
            {
                "event_type": event_type,
                "enabled": policy["enabled"],
                "directions": list(policy["directions"]),
                "phases": list(policy["phases"]),
                "version": self.VERSION,
            }
            for event_type, policy in self.ALLOWED_EVENTS.items()
        ]
