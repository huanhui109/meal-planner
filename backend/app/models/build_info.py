"""小程序版本元信息

存储小程序不同版本的最小版本要求 / 最新版本 / 是否强制升级 / 升级说明。
普通情况小程序发布新版后, 上架新行 + 把 latest_version / min_version 同步升一格。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BuildInfo(Base):
    __tablename__ = "build_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 形如 "0.5.0", 与 miniapp/package.json:version 同步
    version: Mapped[str] = mapped_column(String(20), nullable=False, comment="小程序版本号")
    # 低于这个版本号的小程序启动期必须升级; 形如 "0.5.0"
    min_version: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="低于此版本强制升级"
    )
    # 是否强制升级: true 时启动期直接拦, false 时只弹 toast
    force_update: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否强制升级"
    )
    # 升级文案 / changelog, 富文本或纯文本都行, 前端直接展示
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="升级说明")
    # 跳转链接 (H5 升级页 / 商店 / 下载二维码)
    update_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="跳转链接 (H5 / 商店 / 二维码页)"
    )
    released_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
