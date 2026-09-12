"""反馈相关 Pydantic 模型"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# 类目枚举: 字符串字面量, 与前端 FeedbackCategory 保持一致
FeedbackCategory = Literal["bug", "suggestion", "recipe", "other"]


class FeedbackCreate(BaseModel):
    category: FeedbackCategory = Field(default="other", description="反馈类型")
    content: str = Field(min_length=1, max_length=2000, description="反馈内容")
    contact: Optional[str] = Field(default=None, max_length=100, description="联系方式")
    device_info: Optional[str] = Field(default=None, description="设备信息 JSON 字符串")


class FeedbackOut(BaseModel):
    id: int
    category: str
    content: str
    contact: Optional[str] = None
    created_at: str
    status: str
