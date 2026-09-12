"""FastAPI 依赖注入 - DB Session, 当前用户, Settings"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenError, access_cookie_name, decode_token
from app.config import Settings, get_settings
from app.database import async_session_factory
from app.models.user import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话, 自动 commit/rollback"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings_dep() -> Settings:
    """获取配置单例"""
    return get_settings()


def _extract_token(request: Request) -> str:
    """优先读 Cookie, 其次读 Authorization: Bearer"""
    token = request.cookies.get(access_cookie_name())
    if token:
        return token
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析访问令牌并加载当前用户, 未登录一律 401"""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录, 请先通过飞书扫码登录",
        )
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务端认证配置缺失: {exc}",
        ) from exc
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态已失效, 请重新登录",
        )
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在, 请重新登录",
        )
    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """与 get_current_user 一致, 但未登录时返回 None 而非 401

    用于允许匿名访问的接口 (例如反馈提交、首次启动状态探测)
    """
    token = _extract_token(request)
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError:
        return None
    if not payload or not payload.get("sub"):
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
