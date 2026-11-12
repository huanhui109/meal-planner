from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.meal import MealContext, MealContextPatch, ShortText
from app.services.dish_candidate_skill import DEFAULT_COUNT, MAX_COUNT, MIN_COUNT

Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AssistantAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    instruction: Instruction
    context: MealContext
    expected_revision: int = Field(ge=0)


class CandidateRequest(BaseModel):
    """应用内候选菜品技能：一段模糊描述 → 默认 4 个（3-5）结构化候选。

    ``context`` 只接受白名单条件（服务层再次收敛），``persist=True`` 时由服务端
    按「不得杜撰」的全部校验决定是否写入 recipe 表，模型无权直接落库。
    """

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=DEFAULT_COUNT, ge=MIN_COUNT, le=MAX_COUNT)
    context: dict[str, Any] = Field(default_factory=dict)
    exclude_names: list[str] = Field(default_factory=list, max_length=200)
    named_dish: str = Field(default="", max_length=50)
    persist: bool = False


class ContextReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    phase: Literal["context"]
    context: MealContextPatch


class ProposalReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    phase: Literal["proposal"]
    candidate_keys: list[ShortText] = Field(min_length=1, max_length=6)
    reason: str = Field(min_length=1, max_length=200)


class FailureReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    phase: Literal["context", "proposal"]
    error: str = Field(min_length=1, max_length=300)


class ModelChoiceRequest(BaseModel):
    """User's model selection. An empty ``model`` means "auto"."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="", max_length=100)
    region: Literal["", "cn", "global"] = ""


class LoginStartRequest(BaseModel):
    """Start a browser/QR sign-in. CN is single-homed; global may pin a base."""

    model_config = ConfigDict(extra="forbid")

    region: Literal["cn", "global"] = "cn"
    base: str = Field(default="", max_length=200)
