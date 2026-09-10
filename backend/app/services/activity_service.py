"""活动流水读写

系统为用户做过的事都记一笔: 飞书推送、库存监测、拍照识别。
今日页的流程时间线、我的页的机器人状态卡、拍照识别的每日配额都从这里读。

约定: 只 flush 不 commit, 由 get_db 统一提交 (和其他 service 一致)。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)

CHANNEL_FEISHU = "feishu"
CHANNEL_VISION = "vision"
CHANNEL_SYSTEM = "system"

KIND_DAILY_MENU_PUSH = "daily_menu_push"
KIND_EVENING_CHECK = "evening_check"
KIND_EXPIRY_CHECK = "expiry_check"
KIND_VISION_RECOGNIZE = "vision_recognize"

STATUS_SENT = "sent"
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def _today_start(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now()
    return datetime.combine(current.date(), time.min)


class ActivityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        user_id: int,
        *,
        channel: str,
        kind: str,
        title: str,
        detail: Optional[str] = None,
        status: str = STATUS_SENT,
        occurred_at: Optional[datetime] = None,
    ) -> ActivityLog:
        entry = ActivityLog(
            user_id=user_id,
            channel=channel,
            kind=kind,
            title=title,
            detail=detail,
            status=status,
        )
        if occurred_at is not None:
            entry.occurred_at = occurred_at
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def recent(
        self,
        user_id: int,
        *,
        kinds: Optional[Sequence[str]] = None,
        limit: int = 10,
    ) -> List[ActivityLog]:
        query = select(ActivityLog).where(ActivityLog.user_id == user_id)
        if kinds:
            query = query.where(ActivityLog.kind.in_(list(kinds)))
        query = query.order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def latest_today(self, user_id: int, kind: str) -> Optional[ActivityLog]:
        result = await self.db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.user_id == user_id,
                ActivityLog.kind == kind,
                ActivityLog.occurred_at >= _today_start(),
            )
            .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_today(self, user_id: int, kind: str) -> int:
        """今天的配额计数用, 直接数条数 (多 worker 下也准)"""
        result = await self.db.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.user_id == user_id,
                ActivityLog.kind == kind,
                ActivityLog.occurred_at >= _today_start(),
            )
        )
        return int(result.scalar() or 0)

    @staticmethod
    def day_bounds(day: Optional[date] = None) -> tuple:
        """便于测试注入固定日期"""
        target = day or date.today()
        return datetime.combine(target, time.min), datetime.combine(target, time.max)
