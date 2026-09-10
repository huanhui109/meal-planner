"""JWT 令牌签发/校验与 Cookie 读写"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional

import jwt
from fastapi import Response

from app.config import get_settings

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_OAUTH_STATE = "oauth_state"

MIN_SECRET_LENGTH = 32


class TokenError(Exception):
    """令牌配置或校验异常"""


def access_cookie_name() -> str:
    return get_settings().auth.access_cookie_name


def refresh_cookie_name() -> str:
    return get_settings().auth.refresh_cookie_name


def _secret() -> str:
    secret = get_settings().auth.jwt_secret
    if not secret or len(secret) < MIN_SECRET_LENGTH:
        raise TokenError(f"JWT 密钥未配置或长度不足 {MIN_SECRET_LENGTH} 字符, 请设置 APP__AUTH__JWT_SECRET")
    return secret


def _encode(payload: Dict[str, Any], expires: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    body = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(body, _secret(), algorithm=settings.auth.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "type": TOKEN_TYPE_ACCESS},
        timedelta(minutes=settings.auth.access_token_minutes),
    )


def create_refresh_token(user_id: int) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "type": TOKEN_TYPE_REFRESH},
        timedelta(days=settings.auth.refresh_token_days),
    )


def create_oauth_state(redirect: str = "/") -> str:
    """无状态 OAuth state: 自带过期时间, 免服务端存储"""
    return _encode({"type": TOKEN_TYPE_OAUTH_STATE, "redirect": redirect}, timedelta(minutes=10))


def decode_token(token: str, expected_type: str) -> Optional[Dict[str, Any]]:
    """校验令牌, 失败返回 None (调用方决定 401 文案)"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, _secret(), algorithms=[settings.auth.jwt_algorithm])
    except TokenError:
        raise
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    common = {
        "httponly": True,
        "secure": settings.auth.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    if settings.auth.cookie_domain:
        common["domain"] = settings.auth.cookie_domain
    response.set_cookie(
        access_cookie_name(),
        access_token,
        max_age=settings.auth.access_token_minutes * 60,
        **common,
    )
    response.set_cookie(
        refresh_cookie_name(),
        refresh_token,
        max_age=settings.auth.refresh_token_days * 86400,
        **common,
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (access_cookie_name(), refresh_cookie_name()):
        kwargs: Dict[str, Any] = {"path": "/", "samesite": "lax", "secure": settings.auth.cookie_secure}
        if settings.auth.cookie_domain:
            kwargs["domain"] = settings.auth.cookie_domain
        response.delete_cookie(name, **kwargs)
