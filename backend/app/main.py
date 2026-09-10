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
from app.services.generation_service import GenerationWorker
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)

settings = get_settings()
generation_worker = GenerationWorker(settings)


def _validate_auth_config() -> None:
    """密钥缺失时直接失败, 避免线上签发无效令牌"""
    secret = settings.auth.jwt_secret
    if not secret or len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"APP__AUTH__JWT_SECRET 未配置或长度不足 {MIN_SECRET_LENGTH} 字符, 服务拒绝启动"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    setup_logging(settings.app.debug)
    _validate_auth_config()
    if settings.auth.dev_login_enabled:
        logger.warning(
            "本地开发登录已开启 (APP__AUTH__DEV_LOGIN=true): 任何人凭昵称即可登录, 生产环境务必关闭"
        )
    await init_db()
    await generation_worker.start()
    logger.info("%s 已启动", settings.app.name)
    try:
        yield
    finally:
        await generation_worker.stop()
        await close_db()


app = FastAPI(
    title="AI 每周营养菜谱工具",
    description="基于 AI 的每周营养菜谱自动生成工具, 支持飞书扫码登录与冰箱库存闭环",
    version="0.2.0",
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
    """健康检查 - 含数据库连通性探活"""
    database = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - 健康检查不应抛异常
        database = "error"
        logger.exception("数据库探活失败")
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "app": settings.app.name,
        "database": database,
        "version": app.version,
    }
    if database != "ok":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


register_routes(app)
