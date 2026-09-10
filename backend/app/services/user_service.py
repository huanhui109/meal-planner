"""用户服务 - 第三方身份落库与查询

`user.open_id` 是"第三方身份字符串", 按前缀区分命名空间:
  * `ou_...`  飞书 open_id
  * `wechat:` 微信小程序 openid
  * `dev:`    本地开发登录的昵称
本期不做跨来源账号合并, 同一个人用不同方式登录会得到两个互相隔离的账号。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

DEFAULT_NAME = "用户"


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_open_id(self, open_id: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.open_id == open_id))
        return result.scalar_one_or_none()

    async def upsert_from_identity(self, identity: Dict[str, Any], default_name: str = DEFAULT_NAME) -> User:
        """按 open_id upsert 用户: 首次登录建号, 之后刷新资料与登录时间

        没有新行时只 flush 不 commit, 由调用方 (get_db 或 session_scope) 决定事务边界。
        """
        open_id = identity["open_id"]
        user = await self.get_by_open_id(open_id)
        now = datetime.now()
        if user is None:
            user = User(
                open_id=open_id,
                union_id=identity.get("union_id"),
                name=identity.get("name") or default_name,
                avatar_url=identity.get("avatar_url"),
                last_login_at=now,
            )
            self.db.add(user)
            await self.db.flush()
            return user

        user.name = identity.get("name") or user.name
        user.avatar_url = identity.get("avatar_url") or user.avatar_url
        if identity.get("union_id"):
            user.union_id = identity["union_id"]
        user.last_login_at = now
        await self.db.flush()
        return user

    async def upsert_from_feishu(self, identity: Dict[str, Any]) -> User:
        return await self.upsert_from_identity(identity, default_name="飞书用户")

    async def upsert_from_wechat(self, identity: Dict[str, Any]) -> User:
        return await self.upsert_from_identity(identity, default_name="微信用户")
