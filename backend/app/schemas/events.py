"""事件上报 schema"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class EventBatchItem(BaseModel):
    """单条事件"""

    event_name: str = Field(min_length=1, max_length=64, description="事件名")
    ts: int = Field(description="客户端 Unix 毫秒时间戳")
    properties: Optional[dict[str, Any]] = Field(default=None, description="业务字段")
    app_version: Optional[str] = Field(default=None, max_length=40)
    platform: Optional[str] = Field(default=None, max_length=40)


class EventBatchIn(BaseModel):
    """批量上报

    单批最大 50 条 (防止前端失控性重试)
    """

    events: list[EventBatchItem] = Field(min_length=1, max_length=50)


class EventBatchAck(BaseModel):
    accepted: int
    skipped: int
