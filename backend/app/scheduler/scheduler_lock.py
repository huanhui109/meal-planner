"""跨进程调度锁 - 防止多 worker 重复推送

uvicorn --workers N 会 fork 出 N 个进程, 每个进程都会跑一次 lifespan。
不加锁的话 N 个进程都会注册同一批定时任务, 用户会收到 N 条重复推送。

MySQL 用 GET_LOCK 实现: 锁绑定在连接上, 持锁进程退出或连接断开时自动释放,
不需要额外的心跳或超时清理。单进程场景 (SQLite, 仅测试用) 直接放行。
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

DEFAULT_LOCK_NAME = "meal_planner_scheduler"
LOCK_TIMEOUT_SECONDS = 0


class SchedulerLock:
    """持有调度权的进程标记"""

    def __init__(self, engine: AsyncEngine, name: str = DEFAULT_LOCK_NAME):
        self._engine = engine
        self._name = name
        self._connection: Optional[AsyncConnection] = None
        self._acquired = False

    @property
    def held(self) -> bool:
        return self._acquired

    async def acquire(self) -> bool:
        """尝试拿锁; 拿不到返回 False (调用方据此跳过调度器启动), 重复调用是幂等的"""
        if self._acquired:
            return True
        if self._engine.dialect.name != "mysql":
            logger.info("非 MySQL 方言, 跳过调度锁 (假定单进程): %s", self._engine.dialect.name)
            self._acquired = True
            return True

        connection = await self._engine.connect()
        try:
            result = await connection.execute(
                text("SELECT GET_LOCK(:name, :timeout)"),
                {"name": self._name, "timeout": LOCK_TIMEOUT_SECONDS},
            )
            acquired = result.scalar()
        except Exception:
            await connection.close()
            raise
        if acquired != 1:
            await connection.close()
            logger.warning("调度锁 %s 已被其他进程持有, 本进程不启动定时任务", self._name)
            return False
        self._connection = connection
        self._acquired = True
        return True

    async def release(self) -> None:
        """释放锁并归还连接 (进程退出/关闭数据库前调用)"""
        if not self._acquired:
            return
        connection = self._connection
        self._connection = None
        self._acquired = False
        if connection is None:
            return
        try:
            await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": self._name})
        except Exception:  # noqa: BLE001 - 连接已断时锁会自动释放, 不用让关闭流程失败
            logger.warning("释放调度锁 %s 失败, 连接可能已断开", self._name, exc_info=True)
        finally:
            await connection.close()
