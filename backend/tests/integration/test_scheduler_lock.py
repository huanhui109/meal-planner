"""集成测试: 跨进程调度锁 (防止多 worker 重复推送)"""
from __future__ import annotations

import uuid

import pytest
from app.scheduler.scheduler_lock import SchedulerLock

from tests.conftest import requires_mysql

pytestmark = requires_mysql


@pytest.fixture(autouse=True)
async def _need_mysql_dialect(db_engine):
    """锁基于 MySQL GET_LOCK, 其他方言下是空实现, 跳过"""
    if db_engine.dialect.name != "mysql":
        pytest.skip("非 MySQL 方言, 调度锁为空实现")


def _lock_name() -> str:
    return f"meal_planner_test_lock_{uuid.uuid4().hex[:8]}"


async def test_lock_is_exclusive_and_releasable(db_engine):
    name = _lock_name()
    first = SchedulerLock(db_engine, name=name)
    second = SchedulerLock(db_engine, name=name)

    assert await first.acquire() is True
    assert first.held is True
    assert await first.acquire() is True

    assert await second.acquire() is False
    assert second.held is False

    await first.release()
    assert first.held is False

    assert await second.acquire() is True
    await second.release()


async def test_release_without_acquire_is_noop(db_engine):
    lock = SchedulerLock(db_engine, name=_lock_name())
    await lock.release()
    assert lock.held is False


async def test_lock_held_until_release(db_engine):
    """同一个进程重复 acquire 不会把自己锁死"""
    name = _lock_name()
    holder = SchedulerLock(db_engine, name=name)
    rival = SchedulerLock(db_engine, name=name)

    assert await holder.acquire() is True
    for _ in range(3):
        assert await rival.acquire() is False

    await holder.release()
    assert await rival.acquire() is True
    await rival.release()
