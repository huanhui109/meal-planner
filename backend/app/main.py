"""FastAPI 应用入口"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import register_routes
from app.auth.tokens import MIN_SECRET_LENGTH
from app.config import get_settings
from app.database import close_db, engine, init_db
from app.scheduler.scheduler_lock import SchedulerLock
from app.scheduler.scheduler_manager import SchedulerManager, set_current
from app.services.generation_service import GenerationWorker
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)

settings = get_settings()
generation_worker = GenerationWorker(settings)
scheduler_manager = SchedulerManager(settings)
set_current(scheduler_manager)
scheduler_lock = SchedulerLock(engine)


def _validate_auth_config() -> None:
    """密钥缺失时直接失败, 避免线上签发无效令牌"""
    secret = settings.auth.jwt_secret
    if not secret or len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"APP__AUTH__JWT_SECRET 未配置或长度不足 {MIN_SECRET_LENGTH} 字符, 服务拒绝启动")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    setup_logging(settings.app.debug)
    _validate_auth_config()
    if settings.auth.dev_login:
        logger.warning(
            "本地开发登录已开启 (APP__AUTH__DEV_LOGIN=true): 任何人凭昵称即可登录, 生产环境务必关闭"
        )
    await init_db()
    await generation_worker.start()
    if settings.scheduler.enabled:
        # 多 worker 部署时只有抢到锁的进程才注册定时任务, 否则用户会收到重复推送
        if await scheduler_lock.acquire():
            scheduler_manager.start()
    else:
        logger.info("定时推送未启用 (APP__SCHEDULER__ENABLED=false), 跳过调度器启动")
    logger.info("%s 已启动", settings.app.name)
    try:
        yield
    finally:
        scheduler_manager.shutdown()
        await scheduler_lock.release()
        await generation_worker.stop()
        await close_db()


app = FastAPI(
    title="每周鲜 · AI 营养菜谱",
    description="把一周的饭交给 AI 安排好: 偏好即约束 → 生成周菜单 → 校验营养预算 → 补单 → 做饭扣库存",
    version="0.5.0",
    lifespan=lifespan,
)

if settings.app.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """对外只暴露可读错误, 内部细节写日志"""
    logger.exception("未处理异常 path=%s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": 1, "message": "服务内部错误, 请稍后重试", "detail": None},
    )


@app.get("/api/health")
async def health_check():
    """健康检查 - 含数据库连通性 / 调度器 / 最近事件 / 最近生成 / 当前版本"""
    database = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - 健康检查不应抛异常
        database = "error"
        logger.exception("数据库探活失败")

    scheduler_running = scheduler_manager.running if hasattr(scheduler_manager, "running") else None

    # 最近事件 + 最近生成时间 — 给运维判断 "服务是否还活着" 用
    last_event_at: str | None = None
    last_menu_generate_at: str | None = None
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT MAX(received_at) FROM event"))
            v = row.scalar()
            if v is not None:
                last_event_at = v.isoformat() if hasattr(v, "isoformat") else str(v)
            row = await conn.execute(text("SELECT MAX(created_at) FROM menu"))
            v = row.scalar()
            if v is not None:
                last_menu_generate_at = v.isoformat() if hasattr(v, "isoformat") else str(v)
    except Exception:  # noqa: BLE001 - 健康检查不应抛异常, 但要留痕
        logger.exception("查询最近事件/最近生成时间失败")

    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "app": settings.app.name,
        "database": database,
        "version": app.version,
        "scheduler_running": scheduler_running,
        "last_event_at": last_event_at,
        "last_menu_generate_at": last_menu_generate_at,
    }
    if database != "ok":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


register_routes(app)
