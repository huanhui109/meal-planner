"""L0 / L1 双层开关。

L0: settings.inbound_bridge.enabled (进程启动读取), 关闭时 enabled() 直接返回 False,
    不查库、不触达助手; 旧桥 / 快速推荐 / Skill 连接完全不受影响。
L1: inbound_bridge_config 单行表 id=1, 请求级读取, 置 0 立即切断受理并 cancel_in_flight()。
"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.inbound_bridge import InboundBridgeConfig, InboundTask
from app.services.meal_service import meal_now

from . import ACTIVE_TASK_STATUSES


class BridgeSwitch:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings

    async def _row(self) -> InboundBridgeConfig | None:
        return await self.db.get(InboundBridgeConfig, 1)

    async def enabled(self) -> bool:
        """L0 与 L1 同时为真才放行。L0 为假时短路, 不产生任何查询。"""
        if not self.settings.inbound_bridge.enabled:
            return False
        row = await self._row()
        return bool(row.enabled) if row is not None else False

    async def _set(self, enabled: bool, reason: str | None) -> None:
        row = await self._row()
        if row is None:
            row = InboundBridgeConfig(id=1)
            self.db.add(row)
        row.enabled = enabled
        row.reason = reason[:200] if reason else None
        row.updated_at = meal_now()
        await self.db.flush()

    async def kill(self, reason: str) -> None:
        """紧急停用: 置 L1=0 并断开全部在途任务。"""
        await self._set(False, reason)
        await self.cancel_in_flight(reason)

    async def resume(self) -> None:
        """恢复: 只把 L1 置 1 并清空停用原因, 不自动恢复任何在途任务。"""
        await self._set(True, None)

    async def cancel_in_flight(self, reason: str) -> int:
        """把在途任务统一收敛到 disconnected (原方案不变), 返回受影响条数。

        终态口径与 scripts/inbound_bridge_ctl.py 的 kill、PRD 3.3 状态机一致:
        disconnected = 通道/模块断开; cancelled 只用于**用户主动**取消的那次调整。
        两者都是终止态, 都不会触发 propose, 但混用会让审计与前端文案失准。
        """
        result = await self.db.execute(
            update(InboundTask)
            .where(InboundTask.status.in_(ACTIVE_TASK_STATUSES))
            .values(status="disconnected", error=(reason or "模块已停用，本次调整不会保存；原方案未改变")[:500])
        )
        return int(result.rowcount or 0)
