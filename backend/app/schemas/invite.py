"""邀请 (audit T3.1)"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class InviteCodeOut(BaseModel):
    code: str
    share_path: str
    invite_count: int = Field(description="已成功邀请人数")
    reward_granted: int = Field(default=0, description="已发放的 AI 生成额度")


class InviteRedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)


class InviteRedeemOut(BaseModel):
    ok: bool
    message: str
    reward: Optional[int] = Field(default=None, description="本次到账的 AI 生成额度")
