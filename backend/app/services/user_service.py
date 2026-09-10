"""用户服务 - 飞书身份落库与查询"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_open_id(self, open_id: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.open_id == open_id))
        return result.scalar_one_or_none()

    async def upsert_from_feishu(self, identity: Dict[str, Any]) -> User:
        """飞书登录用户首次进入时建号, 之后刷新资料与登录时间"""
        open_id = identity["open_id"]
        user = await self.get_by_open_id(open_id)
        now = datetime.now()
        if user is None:
            user = User(
                open_id=open_id,
                union_id=identity.get("union_id"),
                name=identity.get("name") or "飞书用户",
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
