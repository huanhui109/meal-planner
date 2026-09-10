"""通用 Pydantic 数据模型"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SuccessResponse(BaseModel):
    """统一成功响应"""
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """统一错误响应"""
    code: int = Field(default=1, ge=1)
    message: str = "error"
    detail: Optional[str] = None


class PaginatedResponse(BaseModel):
    """分页响应"""
    total: int
    page: int
    page_size: int
    items: list[Any] = []
