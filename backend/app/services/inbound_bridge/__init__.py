"""双向唤醒模块服务包。

这里集中放跨文件共享的常量与基础类型 (BridgeReject / scrub), 避免各服务各自硬编码
白名单版本、错误码、在途状态等容易漂移的值。具体服务类在各自子模块中定义。

导入说明: 本文件底部把各服务类再导出一份, 方便 `from app.services.inbound_bridge
import TokenService` 这样的写法; 那些类都只依赖本文件上半部分已定义好的名字, 不存在
循环导入。
"""
from __future__ import annotations

import hashlib

# 白名单版本。与 shared/inboundBridge.ts 的 INBOUND_ALLOWLIST_VERSION 同值,
# 但后端独立硬编码, 绝不 import 前端 TS。
ALLOWLIST_VERSION = "ib-1.0"

SIDE_WEB = "web"
SIDE_ASSISTANT = "assistant"
SIDES = (SIDE_WEB, SIDE_ASSISTANT)

DIRECTIONS = ("web_to_bridge", "assistant_to_bridge", "bridge_to_assistant")
PHASES = ("-", "context", "proposal")
TOKEN_STATES = ("issued", "active", "rotated", "revoked", "expired")
OUTCOMES = ("allowed", "rejected", "rotated", "revoked", "state_change")

# 在途状态: 只有这些能被取消 / 超时; 其余一律是终止态, 且异常终止态都"原方案不变"。
ACTIVE_TASK_STATUSES = (
    "received",
    "waking",
    "awaiting_assistant",
    "awaiting_user_approval",
    "validating",
    "uncertain",
)

# 错误码。用于审计 reason_code 与 BridgeReject.code, 不强制进 HTTP body。
ERR_TOKEN = 1401
ERR_ALLOWLIST = 1403
ERR_NOT_FOUND = 1404
ERR_CONFLICT = 1409
ERR_SCHEMA = 1422
ERR_RATE_LIMIT = 1429
ERR_DISABLED = 1503

# 任何令牌明文前缀都不得出现在对话 / 日志 / URL / 出站 content / 错误输出里。
SENSITIVE_PREFIXES = ("fd_ib_", "fd_skill_", "private-")


def scrub(text: str) -> str:
    """对出站内容与错误输出脱敏: 命中任一敏感前缀即替换为 [redacted]。"""
    for prefix in SENSITIVE_PREFIXES:
        text = text.replace(prefix, "[redacted]")
    return text


def placeholder_id(event_id: str) -> int:
    """为 inbound_audit 占位/审计行生成显式主键。

    迁移 0026 把 id 定为 BigInteger 自增主键: MySQL 的 BIGINT AUTO_INCREMENT 会自动
    补值, 但 SQLite 的 BIGINT PRIMARY KEY 不自增 (只有 INTEGER PRIMARY KEY 才自增),
    插入时 id 会是 NULL 而报 IntegrityError。显式给一个由 event_id 派生的 63 位
    正整数, 两端都能插入; 同一 event_id 幂等, 且重放会先被 SELECT 挡下, 不会走到插入。
    """
    return int.from_bytes(hashlib.sha256(event_id.encode()).digest()[:8], "big") & ((1 << 63) - 1)


class BridgeReject(Exception):
    """服务层统一拒绝异常。

    API 层统一转成 `problem(rej.status, rej.message)`; code 与 reason_code 写进审计,
    对外只暴露可读中文 message, 内部细节与令牌一律不进响应。
    """

    def __init__(self, status: int, code: int, reason_code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.reason_code = reason_code
        self.message = message


from .allowlist import AllowlistRegistry  # noqa: E402
from .audit import AuditService  # noqa: E402
from .gateway import InboundGateway  # noqa: E402
from .orchestrator import WakeOrchestrator  # noqa: E402
from .switch import BridgeSwitch  # noqa: E402
from .tokens import TokenService  # noqa: E402
from .validator import ReceiptValidator  # noqa: E402

__all__ = [
    "ALLOWLIST_VERSION",
    "SIDE_WEB",
    "SIDE_ASSISTANT",
    "SIDES",
    "DIRECTIONS",
    "PHASES",
    "TOKEN_STATES",
    "OUTCOMES",
    "ACTIVE_TASK_STATUSES",
    "ERR_TOKEN",
    "ERR_ALLOWLIST",
    "ERR_NOT_FOUND",
    "ERR_CONFLICT",
    "ERR_SCHEMA",
    "ERR_RATE_LIMIT",
    "ERR_DISABLED",
    "SENSITIVE_PREFIXES",
    "scrub",
    "placeholder_id",
    "BridgeReject",
    "TokenService",
    "AllowlistRegistry",
    "AuditService",
    "BridgeSwitch",
    "InboundGateway",
    "WakeOrchestrator",
    "ReceiptValidator",
]
