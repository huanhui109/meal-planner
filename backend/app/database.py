"""数据库模块 - SQLAlchemy 异步引擎与会话管理 (MySQL 8.0)

表结构由 Alembic 管理, 应用启动只做连通性检查, 不再执行任何 DDL。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()


def build_engine(url: Optional[str] = None) -> AsyncEngine:
    """按 URL 方言构建异步引擎 (MySQL 走连接池, 其他方言保持默认)"""
    target = url or settings.database.url
    kwargs: dict = {
        "echo": settings.database.echo,
        "pool_pre_ping": True,
    }
    if target.startswith("mysql"):
        kwargs.update(
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_recycle=settings.database.pool_recycle,
            pool_timeout=settings.database.pool_timeout,
        )
    return create_async_engine(target, **kwargs)


engine = build_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """启动时的连通性检查 (建表/改表由 alembic upgrade head 负责)"""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """关闭数据库连接池"""
    await engine.dispose()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """独立会话上下文 - 供后台任务/脚本使用, 自带提交与回滚"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
