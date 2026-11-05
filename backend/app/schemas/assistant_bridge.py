from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.meal import MealContext, MealContextPatch, ShortText

Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AssistantAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    instruction: Instruction
    context: MealContext
    expected_revision: int = Field(ge=0)


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
