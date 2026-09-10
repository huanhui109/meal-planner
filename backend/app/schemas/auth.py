"""认证相关 Pydantic 模型"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CurrentUserResponse(BaseModel):
    """当前登录用户"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    open_id: str
    avatar_url: str | None = None


class LoginUrlResponse(BaseModel):
    """飞书授权页地址"""

    authorize_url: str
    state: str


class LoginResultResponse(BaseModel):
    """回调完成后返回的登录用户"""

    user: CurrentUserResponse
    redirect: str = Field(default="/", description="登录后应跳转的前端路径")


class AuthProvidersResponse(BaseModel):
    """当前可用的登录方式, 前端据此决定渲染哪些入口"""

    feishu: bool = Field(description="是否已配置飞书应用, 可扫码登录")
    wechat: bool = Field(default=False, description="是否已配置微信小程序, 可一键登录")
    dev_login: bool = Field(description="是否开启本地开发登录")


class DevLoginRequest(BaseModel):
    """本地开发登录 - 用昵称区分不同用户, 便于验证多用户隔离"""

    name: str = Field(default="本地开发用户", min_length=1, max_length=50)


class WechatMiniLoginRequest(BaseModel):
    """微信小程序登录 - code 来自 wx.login()"""

    code: str = Field(min_length=1, max_length=256, description="wx.login() 返回的临时 code")


class RefreshRequest(BaseModel):
    """Bearer 模式刷新 - 小程序没有可靠的 cookie jar, 用 body 传递刷新令牌"""

    refresh_token: str = Field(min_length=1, description="上一次拿到的 refresh_token")


class TokenBundle(BaseModel):
    """Bearer 模式返回的令牌组 (浏览器端走 httpOnly Cookie, 不看这个)"""

    access_token: str
    refresh_token: str
    expires_in: int = Field(description="access_token 有效秒数")
    user: CurrentUserResponse


class DevLoginResponse(CurrentUserResponse):
    """本地开发登录结果

    保留用户资料在顶层 (H5 直接读 data.name), 同时附上令牌供小程序开发期使用。
    """

    access_token: str
    refresh_token: str
    expires_in: int
