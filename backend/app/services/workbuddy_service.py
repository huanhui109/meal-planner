from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant_bridge import AssistantAdjustment, WorkBuddyConnection
from app.services.meal_service import MealService, meal_now, problem
from app.services.workbuddy_client import WorkBuddyClient, WorkBuddyError

ACTIVE_ADJUSTMENTS = ("sending", "waiting")


class WorkBuddyService:
    def __init__(self, db: AsyncSession, client: WorkBuddyClient):
        self.db = db
        self.client = client

    def cipher(self) -> Fernet:
        settings = self.client.settings
        secret = settings.workbuddy.encryption_key or settings.auth.jwt_secret
        if len(secret) < 32:
            raise WorkBuddyError("助手凭据加密密钥未配置")
        key = hmac.new(secret.encode(), b"fandecide.workbuddy.credentials.v1", hashlib.sha256).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    async def connection(self, user_id: int) -> WorkBuddyConnection | None:
        return (await self.db.execute(
            select(WorkBuddyConnection).where(WorkBuddyConnection.user_id == user_id)
            .with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()

    def credentials(self, connection: WorkBuddyConnection | None) -> dict:
        if (
            connection is None or not connection.credentials
            or connection.client_id != self.client.settings.workbuddy.client_id
        ):
            raise WorkBuddyError("请先授权连接 WorkBuddy", reauthorize=True)
        try:
            return json.loads(self.cipher().decrypt(connection.credentials.encode()))
        except (InvalidToken, ValueError):
            raise WorkBuddyError("助手凭据已失效，请重新连接 WorkBuddy", reauthorize=True) from None

    def store(self, connection: WorkBuddyConnection, token: dict) -> None:
        connection.credentials = self.cipher().encrypt(json.dumps({
            "access_token": token["access_token"], "refresh_token": token.get("refresh_token", ""),
        }).encode()).decode()
        connection.client_id = self.client.settings.workbuddy.client_id
        connection.expires_at = meal_now() + timedelta(seconds=token["expires_in"])

    async def authorize(self, user_id: int) -> str:
        if not self.client.configured:
            problem(503, "尚未配置 WorkBuddy 应用，请由服务管理员完成配置")
        await MealService(self.db).lock_user(user_id)
        connection = await self.connection(user_id)
        if connection is None:
            connection = WorkBuddyConnection(user_id=user_id)
            self.db.add(connection)
        state = secrets.token_urlsafe(32)
        connection.state_hash = hashlib.sha256(state.encode()).hexdigest()
        connection.state_expires_at = meal_now() + timedelta(minutes=10)
        return self.client.authorize_url(state)

    async def callback(self, user_id: int, state: str, code: str, error: str = "") -> None:
        if not self.client.configured:
            problem(503, "尚未配置 WorkBuddy 应用")
        await MealService(self.db).lock_user(user_id)
        connection = await self.connection(user_id)
        digest = hashlib.sha256(state.encode()).hexdigest()
        if (
            not state or connection is None or not connection.state_hash
            or not connection.state_expires_at or connection.state_expires_at <= meal_now()
            or not secrets.compare_digest(digest, connection.state_hash)
        ):
            problem(400, "授权请求已失效，请重新连接")
        connection.state_expires_at = None
        # Consume the single-use state before exchanging the code with the provider.
        await self.db.commit()
        if error or not code:
            raise WorkBuddyError("WorkBuddy 授权未完成")
        token = await self.client.token(code=code)
        await MealService(self.db).lock_user(user_id)
        connection = await self.connection(user_id)
        # A disconnect or a newer authorization must win over this in-flight callback.
        if connection is None or connection.state_hash != digest:
            raise WorkBuddyError("连接状态已改变，请重新授权")
        connection.state_hash = None
        self.store(connection, token)

    async def access_token(self, user_id: int) -> str:
        if not self.client.configured:
            raise WorkBuddyError("尚未配置 WorkBuddy 应用")
        connection = await self.connection(user_id)
        try:
            token = self.credentials(connection)
            if not connection.expires_at or connection.expires_at <= meal_now() + timedelta(seconds=30):
                if not token.get("refresh_token"):
                    raise WorkBuddyError("WorkBuddy 授权已过期，请重新连接", reauthorize=True)
                refreshed = await self.client.token(refresh_token=token["refresh_token"])
                if not refreshed.get("refresh_token"):
                    refreshed["refresh_token"] = token["refresh_token"]
                self.store(connection, refreshed)
                token = refreshed
            return token["access_token"]
        finally:
            # Release the connection lock before any job/user lock or message request.
            await self.db.commit()

    async def status(self, user_id: int) -> dict:
        result = {
            "configured": self.client.configured, "connected": False, "online": None,
            "state": "not_configured", "message": "服务尚未配置 WorkBuddy，仍可复制任务到助手",
        }
        if not self.client.configured:
            return result
        try:
            token = await self.access_token(user_id)
            result["connected"] = True
            online = await self.client.online(token)
            result.update(
                online=online, state="online" if online else "offline",
                message="WorkBuddy 已连接，可以直接发送" if online else "WorkBuddy 离线，请打开电脑上的助手",
            )
        except WorkBuddyError as exc:
            result.update(state="disconnected" if exc.reauthorize else "unavailable", message=str(exc))
            if exc.reauthorize:
                result["connected"] = False
        return result

    async def disconnect(self, user_id: int) -> None:
        await MealService(self.db).lock_user(user_id)
        connection = await self.connection(user_id)
        if connection:
            await self.db.delete(connection)
        jobs = (await self.db.execute(select(AssistantAdjustment).where(
            AssistantAdjustment.user_id == user_id, AssistantAdjustment.status.in_(ACTIVE_ADJUSTMENTS),
        ).with_for_update())).scalars().all()
        for job in jobs:
            job.status = "cancelled"
            job.error = "已断开 WorkBuddy，本次调整不会保存"
