"""事件上报 schema"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class EventBatchItem(BaseModel):
    """单条事件

    ts 是客户端毫秒时间戳, 不可靠。服务端落库时另行记录当前时间 received_at,
    指标一律以 received_at 为准 (详见 models/event.py 模块 docstring)。
    """

    event_name: str = Field(min_length=1, max_length=64, description="事件名")
    ts: int = Field(description="客户端 Unix 毫秒时间戳")
    properties: Optional[dict[str, Any]] = Field(default=None, description="业务字段")
    app_version: Optional[str] = Field(default=None, max_length=40)
    platform: Optional[str] = Field(default=None, max_length=40)
    # V1.2.0 R-06: 会话贯穿。UUIDv4 = 36 字符, 前端进首页生成, 离开 30 分钟后换新
    session_id: Optional[str] = Field(
        default=None, max_length=36, description="会话 ID (前端 UUIDv4)"
    )
    # 决策之后的事件才有 (decide_result_shown 及以后); 结果之前的那几个事件为空
    decision_id: Optional[int] = Field(default=None, description="关联的决策流水 id")
    # V1.2.0 R-16: 首页灰度版本。服务端下发的值优先, 客户端拿不到时为 None
    layout_version: Optional[str] = Field(
        default=None, max_length=20, description="首页灰度版本: v1.1/v1.2"
    )


class EventBatchIn(BaseModel):
    """批量上报

    单批最大 50 条 (防止前端失控性重试)
    """

    events: list[EventBatchItem] = Field(min_length=1, max_length=50)


class EventBatchAck(BaseModel):
    accepted: int
    skipped: int
