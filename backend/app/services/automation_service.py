"""F7 自动化状态 - 我的页里"机器人现在到底在做什么"

只读真实状态, 不做"界面能开但实际不生效"的开关: 推送开关仍然由 .env 的
APP__SCHEDULER__ENABLED 控制, 这里只把它诚实地显示出来。

没有配置 / 没有运行时, 一律降级成"未开启 + 怎么开", 而不是报错。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.user import User
from app.scheduler.scheduler_manager import get_current
from app.services.activity_service import (
    CHANNEL_FEISHU,
    KIND_DAILY_MENU_PUSH,
    KIND_EVENING_CHECK,
    KIND_EXPIRY_CHECK,
    ActivityService,
)

logger = logging.getLogger(__name__)

FEISHU_OPEN_ID_PREFIX = "ou_"


class AutomationService:
    def __init__(self, db: AsyncSession, settings: Optional[Settings] = None):
        self.db = db
        self.settings = settings or get_settings()
        self.activity = ActivityService(db)

    async def status(self, user: User) -> dict:
        return {
            "feishu": await self._feishu(user),
            "scheduler": self._scheduler(),
            "reminders": self._reminders(),
            "notifications": await self._notifications(user),
        }

    # ---------- 飞书机器人 ----------

    async def _feishu(self, user: User) -> dict:
        """飞书机器人的真实状态

        配置来源是「用户自己的配置 > 部署默认配置」(见 FeishuConfigService),
        所以这里直接问配置服务要一份最终视图, 不再只看全局 settings。
        """
        from app.services.feishu_config_service import FeishuConfigService

        config = self.settings.feishu
        view = await FeishuConfigService(self.db, self.settings).view(user)
        webhook = bool(config.verification_token or config.encrypt_key)
        last = await self.activity.latest_today(user.id, KIND_DAILY_MENU_PUSH)
        recent = await self.activity.recent(
            user.id,
            kinds=(KIND_DAILY_MENU_PUSH, KIND_EVENING_CHECK, KIND_EXPIRY_CHECK),
            limit=1,
        )
        latest = last or (recent[0] if recent else None)
        return {
            "configured": view["configured"],
            "enabled": view["enabled"],
            "source": view["source"],
            "webhook_configured": webhook,
            "bound": view["configured"],
            "last_push_at": latest.occurred_at.isoformat(timespec="seconds") if latest else None,
            "last_push_status": latest.status if latest else None,
            "last_push_title": latest.title if latest else None,
        }

    # ---------- 调度器 ----------

    def _scheduler(self) -> dict:
        config = self.settings.scheduler
        manager = get_current()
        jobs: List[dict] = []
        if config.enabled and manager and manager.started:
            jobs = [
                {"id": job["id"], "next_run": job["next_run"], "trigger": job["trigger"]}
                for job in manager.get_jobs_info()
            ]
        return {
            "enabled": config.enabled,
            "running": bool(manager and manager.started),
            "timezone": config.timezone,
            "jobs": jobs,
        }

    def _reminders(self) -> dict:
        config = self.settings.scheduler
        return {
            "daily_menu_push": config.daily_menu_push,
            "evening_check": config.evening_check,
            "expiry_check": config.expiry_check,
            "weekly_generation": config.weekly_generation,
            "weekend_skipped": True,
            "note": "工作日按上面的时间推送; 周末与法定节假日不推送",
        }

    async def _notifications(self, user: User) -> List[dict]:
        entries = await self.activity.recent(user.id, limit=8)
        return [
            {
                "id": entry.id,
                "channel": entry.channel,
                "kind": entry.kind,
                "title": entry.title,
                "detail": entry.detail,
                "status": entry.status,
                "occurred_at": entry.occurred_at.isoformat(timespec="seconds"),
            }
            for entry in entries
        ]

    # ---------- 供 jobs.py 复用 ----------

    def feishu_channel(self) -> str:
        return CHANNEL_FEISHU
