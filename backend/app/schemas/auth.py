"""认证相关 Pydantic 模型"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CurrentUserResponse(BaseModel):
    """当前登录用户"""
    id: int
    name: str
    open_id: str
    avatar_url: str | None = None

    class Config:
        from_attributes = True


class LoginUrlResponse(BaseModel):
    """飞书授权页地址"""
    authorize_url: str
    state: str


class LoginResultResponse(BaseModel):
    """回调完成后返回的登录用户"""
    user: CurrentUserResponse
    redirect: str = Field(default="/", description="登录后应跳转的前端路径")


class AuthProvidersResponse(BaseModel):
    """当前可用的登录方式, 前端据此决定渲染哪些入口"""
    feishu: bool = Field(description="是否已配置飞书应用, 可扫码登录")
    dev_login: bool = Field(description="是否开启本地开发登录")


class DevLoginRequest(BaseModel):
    """本地开发登录 - 用昵称区分不同用户, 便于验证多用户隔离"""
    name: str = Field(default="本地开发用户", min_length=1, max_length=50)
