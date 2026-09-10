"""菜单与生成任务响应模型 (明细以 dict 组装, 此处只描述状态类响应)"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GenerateAcceptedResponse(BaseModel):
    """生成请求被接受或直接复用已有菜单"""
    task_id: Optional[int] = None
    menu_id: Optional[int] = None
    week_start_date: str
    reused: bool = False
    status: str


class GenerationTaskResponse(BaseModel):
    """生成任务状态 (前端轮询)"""
    task_id: int
    status: str
    menu_id: Optional[int] = None
    week_start_date: str
    error: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
