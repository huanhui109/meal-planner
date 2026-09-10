"""用户自己的飞书机器人配置 - 读 / 存 / 测

凭证解析顺序 (与前端"填了就用我的, 没填用部署默认"的文案一致):
  1. 用户在「我的 → 自动化」里填的配置
  2. 部署级配置 (config/default.yaml 的 feishu / 环境变量 APP__FEISHU__*)
  3. 都没有 -> 视为未配置, 前端引导用户去填

密钥只写不读: 存库前用 secret_box 加密, 回给前端的一律是掩码。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.feishu_client import FeishuClient, FeishuClientError
from app.config import Settings, get_settings
from app.models.user import User
from app.models.user_feishu_config import UserFeishuConfig
from app.schemas.automation import FeishuConfigUpdate
from app.services import secret_box

logger = logging.getLogger(__name__)

DEFAULT_RECEIVE_TYPE = "open_id"
VALID_RECEIVE_TYPES = ("open_id", "chat_id", "email")

#: 前端指引里按顺序展示的必填项 (缺哪个就提示哪个)
REQUIRED_FIELDS = ("app_id", "app_secret", "receive_id")

FIELD_LABELS = {
    "app_id": "App ID",
    "app_secret": "App Secret",
    "receive_id": "接收人 ID",
}


@dataclass
class ResolvedCredentials:
    """最终用于发消息的一套凭证"""

    app_id: str
    app_secret: str
    receive_id: str
    receive_id_type: str
    source: str  # user / deployment


class FeishuConfigService:
    def __init__(self, db: AsyncSession, settings: Optional[Settings] = None):
        self.db = db
        self.settings = settings or get_settings()

    # ---------- 读 ----------

    async def get(self, user_id: int) -> Optional[UserFeishuConfig]:
        result = await self.db.execute(select(UserFeishuConfig).where(UserFeishuConfig.user_id == user_id))
        return result.scalar_one_or_none()

    async def view(self, user: User) -> dict:
        """给前端的配置视图 (密钥掩码)"""
        row = await self.get(user.id)
        deployment = self.settings.feishu
        deployment_ready = bool(deployment.app_id and deployment.app_secret)

        if row is not None:
            has_secret = bool(row.app_secret_encrypted)
            missing = [f for f in REQUIRED_FIELDS if not self._field_value(row, f)]
            return {
                "configured": has_secret and not missing,
                "enabled": row.enabled,
                "app_id": row.app_id,
                "app_secret_masked": secret_box.mask(secret_box.decrypt(row.app_secret_encrypted)),
                "has_secret": has_secret,
                "receive_id": row.receive_id,
                "receive_id_type": row.receive_id_type,
                "remark": row.remark,
                "last_verified_at": _iso(row.last_verified_at),
                "last_error": row.last_error,
                "missing_fields": [FIELD_LABELS[f] for f in missing],
                "source": "user",
            }

        # 没配过自己的 -> 展示部署级配置是否可用
        missing = [] if deployment_ready else [FIELD_LABELS["app_id"], FIELD_LABELS["app_secret"]]
        if deployment_ready and not deployment.default_chat_id:
            missing.append(FIELD_LABELS["receive_id"])
        return {
            "configured": deployment_ready,
            "enabled": deployment_ready,
            "app_id": deployment.app_id,
            "app_secret_masked": secret_box.mask(deployment.app_secret),
            "has_secret": bool(deployment.app_secret),
            "receive_id": deployment.default_chat_id,
            "receive_id_type": DEFAULT_RECEIVE_TYPE,
            "remark": "使用部署默认配置",
            "last_verified_at": None,
            "last_error": None,
            "missing_fields": missing,
            "source": "deployment",
        }

    @staticmethod
    def _field_value(row: UserFeishuConfig, field: str) -> str:
        if field == "app_secret":
            return row.app_secret_encrypted
        return getattr(row, field, "") or ""

    # ---------- 写 ----------

    async def save(self, user: User, payload: FeishuConfigUpdate) -> UserFeishuConfig:
        row = await self.get(user.id)
        if row is None:
            row = UserFeishuConfig(user_id=user.id)
            self.db.add(row)

        row.app_id = payload.app_id.strip()
        row.receive_id = payload.receive_id.strip()
        row.receive_id_type = (
            payload.receive_id_type
            if payload.receive_id_type in VALID_RECEIVE_TYPES
            else DEFAULT_RECEIVE_TYPE
        )
        row.remark = payload.remark.strip()
        row.enabled = payload.enabled

        # 只写: 传了才覆盖, 空串/None 都表示"保留原密钥"
        secret = (payload.app_secret or "").strip()
        if secret:
            row.app_secret_encrypted = secret_box.encrypt(secret)

        row.last_error = None
        await self.db.flush()
        return row

    async def clear(self, user: User) -> None:
        row = await self.get(user.id)
        if row is not None:
            await self.db.delete(row)
            await self.db.flush()

    # ---------- 解析 + 发送 ----------

    async def resolve(self, user: User) -> Optional[ResolvedCredentials]:
        """按 user -> deployment 的顺序取出一套可用凭证; 没有则返回 None"""
        row = await self.get(user.id)
        if row is not None and row.enabled:
            secret = _safe_decrypt(row.app_secret_encrypted)
            if row.app_id and secret and row.receive_id:
                return ResolvedCredentials(
                    app_id=row.app_id,
                    app_secret=secret,
                    receive_id=row.receive_id,
                    receive_id_type=row.receive_id_type or DEFAULT_RECEIVE_TYPE,
                    source="user",
                )

        deployment = self.settings.feishu
        if deployment.app_id and deployment.app_secret and deployment.default_chat_id:
            return ResolvedCredentials(
                app_id=deployment.app_id,
                app_secret=deployment.app_secret,
                receive_id=deployment.default_chat_id,
                receive_id_type=DEFAULT_RECEIVE_TYPE,
                source="deployment",
            )
        return None

    def build_client(
        self, creds: ResolvedCredentials, client: Optional[httpx.AsyncClient] = None
    ) -> FeishuClient:
        """用指定凭证构造客户端 (测试可注入 httpx client)"""
        return FeishuClient(
            self.settings,
            client=client,
            app_id=creds.app_id,
            app_secret=creds.app_secret,
        )

    async def send_text(
        self,
        user: User,
        text: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> tuple[bool, str]:
        """按用户配置发一条文本, 并把结果记到配置行上"""
        creds = await self.resolve(user)
        if creds is None:
            return False, "还没有可用的飞书配置, 请先填写 App ID / App Secret / 接收人 ID"

        bot = self.build_client(creds, client=client)
        try:
            await bot.send_text(creds.receive_id, text, receive_id_type=creds.receive_id_type)
        except FeishuClientError as exc:
            await self._record_result(user, None, str(exc))
            return False, str(exc)

        await self._record_result(user, datetime.now(), None)
        return True, "测试消息已发送, 请到飞书查看"

    async def _record_result(self, user: User, verified_at: Optional[datetime], error: Optional[str]) -> None:
        row = await self.get(user.id)
        if row is None:
            return
        if verified_at is not None:
            row.last_verified_at = verified_at
        row.last_error = error
        await self.db.flush()


def _safe_decrypt(token: str) -> str:
    try:
        return secret_box.decrypt(token)
    except secret_box.SecretBoxError as exc:
        logger.warning("解密飞书 App Secret 失败: %s", exc)
        return ""


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") if value else None
