"""小程序版本元信息 schema"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BuildInfoOut(BaseModel):
    """前端启动期拿到的版本元信息

    前端据此决定:
    - force_update=true → 强制挡住, 跳更新页
    - force_update=false + 当前版本 < min_version → 弹 toast 提示升级, 不挡操作
    - 当前版本 ≥ min_version → 静默放行
    """

    latest_version: str = Field(description="最新版本号")
    min_version: str = Field(description="要求的最低版本号, 低于此版本强制升级")
    force_update: bool = Field(description="是否强制升级")
    update_url: Optional[str] = Field(default=None, description="更新页 / 商店跳转链接")
    notes: Optional[str] = Field(default=None, description="升级说明文案")
