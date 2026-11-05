from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meal import AssistantGrant
from app.services.meal_service import meal_now, problem

ASSISTANT_SCOPES = ("meal:read", "meal:propose")


class AssistantService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def view(grant: AssistantGrant) -> dict:
        return {
            "id": grant.id, "name": grant.name, "scopes": list(ASSISTANT_SCOPES),
            "created_at": grant.created_at.isoformat() if grant.created_at else None,
            "expires_at": grant.expires_at.isoformat(),
            "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        }

    async def create(self, user_id: int, name: str) -> dict:
        token = f"fd_skill_{secrets.token_urlsafe(32)}"
        grant = AssistantGrant(
            id=str(uuid4()), user_id=user_id, name=name.strip() or "饭决 Skill",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=meal_now() + timedelta(days=90),
        )
        self.db.add(grant)
        await self.db.flush()
        await self.db.refresh(grant)
        return {**self.view(grant), "token": token}

    async def list(self, user_id: int) -> list[dict]:
        rows = (await self.db.execute(select(AssistantGrant).where(
            AssistantGrant.user_id == user_id,
        ).order_by(AssistantGrant.created_at.desc()))).scalars().all()
        return [self.view(row) for row in rows]

    async def revoke(self, user_id: int, grant_id: str) -> None:
        grant = (await self.db.execute(select(AssistantGrant).where(
            AssistantGrant.id == grant_id, AssistantGrant.user_id == user_id,
        ).with_for_update())).scalar_one_or_none()
        if grant is None:
            problem(404, "找不到这个助手连接")
        grant.revoked_at = grant.revoked_at or meal_now()
        await self.db.flush()

    async def authenticate(self, token: str) -> int:
        if not token.startswith("fd_skill_") or len(token) > 100:
            problem(401, "助手连接凭证无效，请重新连接")
        grant = (await self.db.execute(select(AssistantGrant).where(
            AssistantGrant.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        ).with_for_update())).scalar_one_or_none()
        if grant is None or grant.revoked_at or grant.expires_at <= meal_now():
            problem(401, "助手连接已撤销或过期，请在饭决中重新连接")
        return grant.user_id
