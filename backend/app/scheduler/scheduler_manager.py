"""APScheduler 生命周期管理"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings

logger = logging.getLogger(__name__)


class SchedulerManager:
    """管理 APScheduler 的启动和关闭"""

    def __init__(self):
        settings = get_settings()
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )

    def start(self):
        """注册所有定时任务并启动调度器"""
        self._register_jobs()
        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler shutdown")

    def _register_jobs(self):
        """注册定时任务 (Sprint 6+ 完善 job 逻辑)"""
        pass

    def get_jobs_info(self) -> list:
        """获取所有任务信息"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs
