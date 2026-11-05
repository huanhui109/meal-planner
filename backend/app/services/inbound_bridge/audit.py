"""审计服务 - 字段白名单可枚举, 绝不写令牌明文 / 对话全文 / 菜品明细。

inbound_audit.event_id 同时是防重放键: TokenService.consume_event_id 先插入一条占位行
(outcome 为空串), 本服务的 record() 再用真实字段把它补齐, 因此一次事件只产生一行。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbound_bridge import InboundAudit
from app.services.meal_service import meal_now

from . import placeholder_id


class AuditService:
    """只允许写入 SAFE_FIELDS 列出的列; 其它列一律不碰。"""

    SAFE_FIELDS = (
        "event_id",
        "user_id",
        "pair_id",
        "task_id",
        "direction",
        "event_type",
        "outcome",
        "reason_code",
        "allowlist_version",
        "created_at",
    )

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, event_id, user_id, outcome, reason_code, envelope) -> None:
        """记录一次允许/拒绝: 占位行存在则补齐, 存在则更新为本次最终结论。

        重放请求不会走到这里 —— 网关在 consume_event_id 判重后直接拒绝且不记审计,
        因此不会覆盖该 event_id 的原始记录。
        """
        row = (await self.db.execute(
            select(InboundAudit).where(InboundAudit.event_id == event_id)
        )).scalar_one_or_none()
        if row is None:
            # 显式主键: 兼容 SQLite 的 BIGINT 主键不自增 (见 __init__.placeholder_id)。
            row = InboundAudit(id=placeholder_id(event_id), event_id=event_id)
            self.db.add(row)
        env = envelope
        row.user_id = user_id
        row.pair_id = (getattr(env, "pair_id", None) if env is not None else None)
        row.task_id = ((getattr(env, "task_id", "") or None) if env is not None else None)
        row.direction = ((getattr(env, "direction", "") if env is not None else "")[:24])
        row.event_type = ((getattr(env, "event_type", "") if env is not None else "")[:60])
        row.outcome = outcome[:16]
        row.reason_code = (reason_code or "")[:40]
        row.allowlist_version = ((getattr(env, "allowlist_version", "") if env is not None else "")[:20])
        await self.db.flush()

    async def list_for_user(self, user_id: int, limit: int) -> list[dict]:
        """仅返回该用户自己的记录, 且只含 SAFE_FIELDS。created_at 转 ISO 字符串。"""
        rows = (await self.db.execute(
            select(InboundAudit)
            .where(InboundAudit.user_id == user_id)
            .order_by(InboundAudit.created_at.desc(), InboundAudit.id.desc())
            .limit(limit)
        )).scalars().all()
        result = []
        for row in rows:
            item = {}
            for field in self.SAFE_FIELDS:
                value = getattr(row, field, None)
                if field == "created_at" and value is not None:
                    value = value.isoformat()
                item[field] = value
            result.append(item)
        return result

    async def purge_expired(self, retention_days: int) -> int:
        """删除超过保留期的审计行, 返回删除条数。"""
        cutoff = meal_now() - timedelta(days=retention_days)
        result = await self.db.execute(
            delete(InboundAudit).where(InboundAudit.created_at < cutoff)
        )
        return int(result.rowcount or 0)
