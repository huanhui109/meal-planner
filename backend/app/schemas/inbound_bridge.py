"""双向唤醒模块契约 - envelope / 各事件 data / 只读视图。

全部模型 extra="forbid": 任何多余字段 (尤其是 user_id) 一律拒收, 用户归属由
服务端从 pair_id 解析绑定, 防止客户端伪造。长度上限沿用 schemas/assistant_bridge.py:
instruction <= 2000 / reason <= 200 / error <= 300 / candidate_keys 1..6。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.meal import MealContext, MealContextPatch, ShortText

# 36 = UUIDv4 带连字符的标准长度, 与各表 varchar(36) 对齐
IdStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
# 触发类事件 task_id 允许为空字符串, 回执类必填 (由 validator 按 phase 复核)
TaskIdStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=36)]
Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ShortField = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
EventTypeField = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
PhaseField = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
NonceField = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
VersionField = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
SigField = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class InboundEnvelope(BaseModel):
    """入站事件信封。禁止出现 user_id (extra="forbid")。

    data 是数据通道, 与指令通道物理分离; canonical 串对其做排序哈希, 因此任何
    多余字段 / NaN 都会在签名或 schema 校验阶段被拒。
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    v: Literal[1] = 1
    pair_id: IdStr
    direction: ShortField
    event_type: EventTypeField
    event_id: IdStr
    task_id: TaskIdStr = ""
    phase: PhaseField
    assistant_instance_id: IdStr
    session_id: IdStr
    issued_at: int
    nonce: NonceField
    sig: SigField
    data: dict
    allowlist_version: VersionField


# ---------------------------------------------------------------- data schemas

class AdjustRequestedData(BaseModel):
    """meal.adjust.requested 的 data。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request_id: UUID
    instruction: Instruction
    context: MealContext
    expected_revision: int = Field(ge=0)


class CancelData(BaseModel):
    """meal.adjust.cancelled / meal.adjust.status_queried 的 data (同为 task_id)。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    task_id: UUID


class ContextReplyData(BaseModel):
    """assistant.context_replied 的 data (条件补丁阶段)。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request_id: UUID
    phase: Literal["context"]
    context: MealContextPatch


class ProposalReplyData(BaseModel):
    """assistant.proposal_replied 的 data (真实候选 key 组合阶段)。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request_id: UUID
    phase: Literal["proposal"]
    candidate_keys: list[ShortText] = Field(min_length=1, max_length=6)
    reason: str = Field(min_length=1, max_length=200)


class FailureReplyData(BaseModel):
    """assistant.failed 的 data (两阶段都允许)。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request_id: UUID
    phase: Literal["context", "proposal"]
    error: str = Field(min_length=1, max_length=300)


# ---------------------------------------------------------------- 只读视图

class PairView(BaseModel):
    """令牌对状态视图 (绝不含明文 / 密文 / 哈希)。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    pair_id: str
    user_id: int
    assistant_instance_id: str
    session_id: str
    web_state: str
    assistant_state: str
    allowlist_version: str
    issued_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    rotated_at: Optional[datetime] = None
    web_revoked_at: Optional[datetime] = None
    assistant_revoked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class TaskView(BaseModel):
    """任务状态视图。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    task_id: str
    user_id: int
    pair_id: str
    session_id: str
    assistant_instance_id: str
    event_type: str
    phase: str
    status: str
    instruction: str
    expected_revision: int
    message_id: Optional[str] = None
    error: Optional[str] = None
    proposal_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    poll_failures: int = 0
    created_at: Optional[datetime] = None


class AuditView(BaseModel):
    """审计记录视图 (仅 SAFE_FIELDS)。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    event_id: str
    user_id: int
    pair_id: Optional[str] = None
    task_id: Optional[str] = None
    direction: str
    event_type: str
    outcome: str
    reason_code: str
    allowlist_version: str
    created_at: Optional[datetime] = None


class AllowlistView(BaseModel):
    """白名单枚举视图。"""

    model_config = ConfigDict(extra="forbid")

    version: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    enabled: bool = True
