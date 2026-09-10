"""调度器生命周期与任务注册的单元测试 (不连数据库)"""
from __future__ import annotations

from app.config import SchedulerSettings, Settings
from app.scheduler.scheduler_manager import SchedulerManager

ALL_JOB_IDS = {
    "push_daily_menu",
    "evening_inventory_check",
    "daily_expiry_check",
    "generate_weekly_menu",
    "daily_scrape_products",
}


def _settings(**overrides) -> Settings:
    """基于真实配置构造, 只覆盖调度相关字段"""
    settings = Settings.load()
    settings.scheduler = SchedulerSettings(enabled=True, **overrides)
    return settings


async def test_start_registers_all_jobs():
    manager = SchedulerManager(_settings())
    manager.start()
    try:
        assert manager.started is True
        jobs = manager.get_jobs_info()
        assert {job["id"] for job in jobs} == ALL_JOB_IDS
        assert all(job["next_run"] for job in jobs)
    finally:
        manager.shutdown()
    assert manager.started is False


async def test_start_is_idempotent():
    manager = SchedulerManager(_settings())
    manager.start()
    manager.start()
    try:
        assert len(manager.get_jobs_info()) == len(ALL_JOB_IDS)
    finally:
        manager.shutdown()


async def test_shutdown_without_start_is_noop():
    manager = SchedulerManager(_settings())
    manager.shutdown()
    assert manager.started is False


async def test_disabled_specs_are_skipped():
    manager = SchedulerManager(_settings(daily_menu_push="", evening_check="off"))
    manager.start()
    try:
        ids = {job["id"] for job in manager.get_jobs_info()}
        assert ids == {"daily_expiry_check", "generate_weekly_menu", "daily_scrape_products"}
    finally:
        manager.shutdown()


async def test_invalid_spec_is_skipped_without_breaking_others(caplog):
    manager = SchedulerManager(_settings(daily_scrape="abc"))
    with caplog.at_level("ERROR"):
        manager.start()
    try:
        ids = {job["id"] for job in manager.get_jobs_info()}
        assert "daily_scrape_products" not in ids
        assert ids == ALL_JOB_IDS - {"daily_scrape_products"}
        assert any("daily_scrape_products" in record.message for record in caplog.records)
    finally:
        manager.shutdown()


async def test_timezone_is_applied_to_trigger():
    manager = SchedulerManager(_settings(expiry_check="10:00", timezone="Asia/Shanghai"))
    manager.start()
    try:
        job = next(item for item in manager.get_jobs_info() if item["id"] == "daily_expiry_check")
        assert str(manager.timezone) == "Asia/Shanghai"
        assert "hour='10'" in job["trigger"]
    finally:
        manager.shutdown()
