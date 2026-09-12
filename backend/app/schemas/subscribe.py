"""订阅消息 schema"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SubscribeTemplate(BaseModel):
    """小程序能授权的订阅模板"""

    template_id: str = Field(description="微信后台模板 ID")
    title: str = Field(description="模板标题, 用户可见")
    description: str = Field(description="模板说明, 用户可见")
    # 关键字: 用于前端预览, 例如 ["菜品", "送达时间"]
    keywords: list[str] = Field(default_factory=list)
    # 一次性 (false) vs 长期 (true); 长期需要后台申请 + 微信审核
    persistent: bool = Field(default=False)
    # 触发场景说明 (前端用于"何时会推送"提示)
    trigger: str = Field(default="")


class SubscribeTemplateListOut(BaseModel):
    items: list[SubscribeTemplate] = Field(default_factory=list)


class SubscribeGrantIn(BaseModel):
    template_id: str = Field(min_length=1, max_length=100)
    # 一次性订阅时 grant=true; 长期订阅用户主动撤授权时 grant=false
    grant: bool = Field(default=True)
    # 前端传给后端的实际授权结果 (来自 Taro.requestSubscribeMessage)
    accepted: Optional[str] = Field(
        default=None, description="用户弹窗结果: 'accept' / 'deny' / 'ban'"
    )


class SubscribeStatusOut(BaseModel):
    template_id: str
    granted: bool
    last_send_at: Optional[str] = None
    last_declined_at: Optional[str] = None
