"""APScheduler 生命周期管理

只负责"什么时候跑", 具体做什么在 jobs.py。
时间写法 (见 SchedulerSettings 注释): "HH:MM" / "DAY HH:MM" / 5 段 crontab / 留空表示不注册。
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings, get_settings
from app.scheduler import jobs

logger = logging.getLogger(__name__)

DISABLED_SPECS = {"", "off", "none", "disabled", "false"}

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def build_trigger(spec: str, timezone: ZoneInfo) -> Optional[CronTrigger]:
    """把配置里的时间写法转成 CronTrigger; 留空/off 返回 None, 格式错误抛 ValueError"""
    raw = (spec or "").strip()
    if raw.lower() in DISABLED_SPECS:
        return None

    parts = raw.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(raw, timezone=timezone)

    if len(parts) == 2:
        day, clock = parts
        weekday = day.strip().lower()[:3]
        if weekday not in WEEKDAY_NAMES:
            raise ValueError(f"星期写法不认识: {day!r} (可用 mon..sun)")
        hour, minute = _parse_clock(clock)
        return CronTrigger(day_of_week=weekday, hour=hour, minute=minute, timezone=timezone)

    if len(parts) == 1:
        hour, minute = _parse_clock(parts[0])
        return CronTrigger(hour=hour, minute=minute, timezone=timezone)

    raise ValueError(f"时间格式不认识: {spec!r} (示例: 08:00 / SUN 20:00 / '30 17 * * 1-5')")


def _parse_clock(value: str) -> Tuple[int, int]:
    pieces = value.split(":")
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        raise ValueError(f"时间格式不认识: {value!r} (应为 HH:MM)")
    hour, minute = int(pieces[0]), int(pieces[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间超出范围: {value!r}")
    return hour, minute


class SchedulerManager:
    """管理 APScheduler 的启动和关闭

    start() 内部不再判断 settings.scheduler.enabled, 由调用方决定是否启动
    (main.py 会判断), 这样它本身可以独立测试。
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.timezone = ZoneInfo(self.settings.scheduler.timezone)
        self.scheduler = AsyncIOScheduler(
            timezone=self.timezone,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def _job_specs(self) -> List[Tuple[str, str, Callable]]:
        config = self.settings.scheduler
        return [
            ("push_daily_menu", config.daily_menu_push, jobs.push_daily_menu),
            ("evening_inventory_check", config.evening_check, jobs.evening_inventory_check),
            ("daily_expiry_check", config.expiry_check, jobs.daily_expiry_check),
            ("generate_weekly_menu", config.weekly_generation, jobs.generate_weekly_menu),
            ("daily_scrape_products", config.daily_scrape, jobs.daily_scrape_products),
            ("enrich_recipes", config.recipe_enrich, jobs.enrich_recipes),
        ]

    def start(self) -> None:
        """注册所有定时任务并启动调度器"""
        if self._started:
            return
        self._register_jobs()
        self.scheduler.start()
        self._started = True
        logger.info(
            "调度器已启动 (时区 %s): %s",
            self.settings.scheduler.timezone,
            ", ".join(job["id"] for job in self.get_jobs_info()) or "无任务",
        )

    def shutdown(self) -> None:
        """关闭调度器"""
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False
        logger.info("调度器已停止")

    def _register_jobs(self) -> None:
        for job_id, spec, func in self._job_specs():
            try:
                trigger = build_trigger(spec, self.timezone)
            except ValueError as exc:
                logger.error("任务 %s 的时间配置无效, 已跳过: %s", job_id, exc)
                continue
            if trigger is None:
                logger.info("任务 %s 未配置时间, 已跳过", job_id)
                continue
            self.scheduler.add_job(func, trigger=trigger, id=job_id, name=job_id, replace_existing=True)

    def get_jobs_info(self) -> list:
        """获取所有任务信息"""
        jobs_info = []
        for job in self.scheduler.get_jobs():
            jobs_info.append(
                {
                    "id": job.id,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs_info


# 运行中的实例: automation_service 要读"下一次什么时候跑"给用户看。
# 用注册表而不是 from app.main import scheduler_manager, 否则 service <- main 会成环。
_current: Optional[SchedulerManager] = None


def set_current(manager: SchedulerManager) -> None:
    global _current
    _current = manager


def get_current() -> Optional[SchedulerManager]:
    return _current
