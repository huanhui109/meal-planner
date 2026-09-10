"""认证 API - 飞书扫码登录"""

from __future__ import annotations

import logging
from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.feishu_oauth import (
    FeishuAuthError,
    FeishuOAuthClient,
    get_feishu_oauth_client,
)
from app.auth.tokens import (
    TOKEN_TYPE_OAUTH_STATE,
    TOKEN_TYPE_REFRESH,
    TokenError,
    clear_auth_cookies,
    create_access_token,
    create_oauth_state,
    create_refresh_token,
    decode_token,
    refresh_cookie_name,
    set_auth_cookies,
)
from app.auth.wechat_oauth import (
    WechatAuthError,
    WechatMiniClient,
    get_wechat_mini_client,
)
from app.config import get_settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    AuthProvidersResponse,
    CurrentUserResponse,
    DevLoginRequest,
    DevLoginResponse,
    RefreshRequest,
    TokenBundle,
    WechatMiniLoginRequest,
)
from app.schemas.common import SuccessResponse
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

DEV_OPEN_ID_PREFIX = "dev:"


def _access_token_ttl() -> int:
    """access_token 有效秒数, 给小程序端算续期时机"""
    return get_settings().auth.access_token_minutes * 60


def _issue_bearer_tokens(user: User) -> Dict[str, Any]:
    """Bearer 模式的令牌组 (小程序用; 浏览器端走 httpOnly Cookie)"""
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "expires_in": _access_token_ttl(),
        "user": CurrentUserResponse.model_validate(user),
    }


@router.get("/feishu/login-url", response_model=SuccessResponse)
async def feishu_login_url(
    redirect: str = "/",
    client: FeishuOAuthClient = Depends(get_feishu_oauth_client),
):
    """获取飞书授权页地址 (PC 展示二维码, 手机端直接唤起飞书)"""
    try:
        state = create_oauth_state(redirect or "/")
        url = client.build_authorize_url(state)
    except (FeishuAuthError, TokenError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return SuccessResponse(
        code=0,
        message="success",
        data={"authorize_url": url, "state": state},
    )


@router.get("/feishu/callback", include_in_schema=False)
async def feishu_callback(
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
    client: FeishuOAuthClient = Depends(get_feishu_oauth_client),
):
    """飞书授权回调: 换 token -> upsert 用户 -> 写入登录 Cookie -> 跳回前端"""
    settings = get_settings()
    redirect = settings.feishu.login_success_redirect or "/"
    if state:
        try:
            payload = decode_token(state, expected_type=TOKEN_TYPE_OAUTH_STATE)
        except TokenError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
        if payload is None:
            return _error_redirect(redirect, "登录状态已过期, 请重新扫码")
        redirect = payload.get("redirect") or redirect

    if not code:
        return _error_redirect(redirect, "缺少授权码, 请重新扫码")

    try:
        identity = await client.login(code)
    except FeishuAuthError as exc:
        return _error_redirect(redirect, str(exc))

    user = await UserService(db).upsert_from_feishu(identity)
    await db.commit()

    response = RedirectResponse(url=redirect, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    set_auth_cookies(response, create_access_token(user.id), create_refresh_token(user.id))
    return response


@router.post("/refresh", response_model=SuccessResponse)
async def refresh_session(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """用刷新令牌换取新的访问令牌 (同时轮换刷新令牌)

    两条通道:
      * 浏览器: 读 httpOnly Cookie, 新令牌写回 Cookie, 响应体只带用户资料
      * 小程序: body 传 refresh_token, 新令牌直接在响应体里返回
        (小程序没有可靠的 cookie jar, 只能自己存)
    """
    body_token = (payload.refresh_token if payload else "").strip()
    token = body_token or request.cookies.get(refresh_cookie_name(), "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效, 请重新登录")
    try:
        payload = decode_token(token, expected_type=TOKEN_TYPE_REFRESH)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务端认证配置缺失: {exc}",
        ) from exc
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效, 请重新登录")
    user = await UserService(db).get_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在, 请重新登录")
    if body_token:
        return SuccessResponse(code=0, message="success", data=_issue_bearer_tokens(user))
    set_auth_cookies(response, create_access_token(user.id), create_refresh_token(user.id))
    return SuccessResponse(
        code=0,
        message="success",
        data=CurrentUserResponse.model_validate(user).model_dump(),
    )


@router.post("/logout", response_model=SuccessResponse)
async def logout(response: Response):
    """清除登录 Cookie"""
    clear_auth_cookies(response)
    return SuccessResponse(code=0, message="已退出登录")


@router.get("/me", response_model=SuccessResponse)
async def me(user: User = Depends(get_current_user)):
    """当前登录用户资料"""
    return SuccessResponse(
        code=0,
        message="success",
        data=CurrentUserResponse.model_validate(user).model_dump(),
    )


@router.get("/providers", response_model=SuccessResponse)
async def auth_providers(
    client: FeishuOAuthClient = Depends(get_feishu_oauth_client),
    wechat: WechatMiniClient = Depends(get_wechat_mini_client),
):
    """登录方式探测 - 前端据此决定渲染飞书扫码、微信一键登录还是本地开发登录"""
    settings = get_settings()
    return SuccessResponse(
        code=0,
        message="success",
        data=AuthProvidersResponse(
            feishu=client.configured and bool(settings.feishu.redirect_uri),
            wechat=wechat.configured,
            dev_login=settings.auth.dev_login,
        ).model_dump(),
    )


@router.post("/wechat/mini-login", response_model=SuccessResponse)
async def wechat_mini_login(
    payload: WechatMiniLoginRequest,
    db: AsyncSession = Depends(get_db),
    client: WechatMiniClient = Depends(get_wechat_mini_client),
):
    """微信小程序一键登录

    小程序 `wx.login()` 拿 code -> 这里换 openid -> upsert 用户 -> 直接返回令牌。
    不写 Cookie: 小程序端把令牌存 storage, 之后每个请求带 Authorization: Bearer。
    """
    # 没配 AppID/Secret 是服务端没准备好, 不是用户的 code 有问题, 所以用 503 而不是 401
    if not client.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="微信小程序未配置, 请设置 APP__WECHAT__APP_ID / APP__WECHAT__APP_SECRET",
        )

    try:
        identity = await client.login(payload.code)
    except WechatAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await UserService(db).upsert_from_wechat(identity)
    await db.commit()
    logger.info("微信小程序登录成功: 用户 id=%s", user.id)
    return SuccessResponse(
        code=0,
        message="success",
        data=TokenBundle(**_issue_bearer_tokens(user)).model_dump(),
    )


@router.post("/dev-login", response_model=SuccessResponse)
async def dev_login(
    payload: DevLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """本地开发登录 - 仅在 APP__AUTH__DEV_LOGIN=true 时可用, 生产必须关闭"""
    if not get_settings().auth.dev_login:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="本地开发登录未开启")
    name = payload.name.strip()
    user = await UserService(db).upsert_from_feishu(
        {
            "open_id": f"{DEV_OPEN_ID_PREFIX}{name}",
            "union_id": None,
            "name": name,
            "avatar_url": None,
        }
    )
    await db.commit()
    set_auth_cookies(response, create_access_token(user.id), create_refresh_token(user.id))
    logger.warning("本地开发登录已使用: 用户=%s (id=%s)", name, user.id)
    return SuccessResponse(
        code=0,
        message="已登录 (本地开发模式)",
        data=DevLoginResponse(
            **CurrentUserResponse.model_validate(user).model_dump(),
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            expires_in=_access_token_ttl(),
        ).model_dump(),
    )


def _error_redirect(redirect: str, message: str) -> RedirectResponse:
    """登录失败时带回可读原因, 由前端展示"""
    separator = "&" if "?" in redirect else "?"
    target = f"{redirect}{separator}login_error={quote(message, safe='')}"
    return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
