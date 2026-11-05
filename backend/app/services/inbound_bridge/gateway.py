"""入站网关 - 三级默认拒绝校验链。

    L0/L1 开关短路 (停用不查库、不记审计、不唤醒)
      -> 第 1 级 身份: TokenService.verify (签名 / 时间窗 / event_id 去重 / 五态 / 绑定)
      -> 第 2 级 事件: AllowlistRegistry.check (禁止清单 / 枚举 / 方向 / 阶段 / 版本)
      -> 第 3 级 业务: 幂等 / 归属 / 阶段 的复核与审计

第 3 级里与具体任务相关的检查 (task 存在、归属隔离、四元匹配、revision、eaten、
二次校验) 由 API 层与 ReceiptValidator 完成 —— 网关刻意不建任务、不 propose。
任一拒绝都记审计, 由 API 把 BridgeReject 转成 problem(status, message)。
"""
from __future__ import annotations

from app.schemas.inbound_bridge import InboundEnvelope

from . import ERR_ALLOWLIST, ERR_DISABLED, BridgeReject


class InboundGateway:
    def __init__(self, db, tokens, allowlist, audit, switch):
        self.db = db
        self.tokens = tokens
        self.allowlist = allowlist
        self.audit = audit
        self.switch = switch

    async def admit(self, envelope: InboundEnvelope, side: str, user) -> tuple:
        """返回 (验签后的 pair, 规范化 envelope)。不建任务、不 propose、不唤醒。"""
        # ---- L0/L1 开关短路: 停用 100% 拒绝, 且不查库 ----
        if not await self.switch.enabled():
            raise BridgeReject(503, ERR_DISABLED, "disabled_reject", "双向唤醒模块已停用")

        # ---- 第 1 级 身份 + 第 2 级 事件白名单 ----
        try:
            pair = await self.tokens.verify(
                envelope, side, user.id if user is not None else None
            )
            self.allowlist.check(
                envelope.event_type,
                envelope.direction,
                envelope.phase,
                envelope.allowlist_version,
            )
        except BridgeReject as rej:
            # 拒绝记审计。拒绝会让请求以 HTTPException 结束, get_db 随即 rollback,
            # 所以这里必须独立提交一次: 既保住审计行, 也保住 consume_event_id 的
            # 防重放占位行 (否则同一 event_id 可被反复重试)。审计失败不得掩盖拒绝本身。
            if rej.reason_code != "replay":
                # 重放不记审计: 那个 event_id 的原始记录 (可能是 allowed) 必须原样保留。
                try:
                    await self.audit.record(
                        envelope.event_id,
                        user.id if user is not None else 0,
                        "rejected",
                        rej.reason_code,
                        envelope,
                    )
                    await self.db.commit()
                except Exception:  # noqa: BLE001 - 审计写入失败不影响拒绝
                    pass
            raise

        # ---- 第 3 级 通过: 幂等(event_id 已在 verify 消费) / 归属(expected_user_id
        #      已在 verify 绑定) / 阶段(已在 allowlist 校验) 均成立, 记 allowed 审计 ----
        await self.audit.record(envelope.event_id, pair.user_id, "allowed", "allowed", envelope)
        return pair, envelope

    def reject(self, reason_code: str) -> None:
        """默认拒绝辅助: 抛 403/1403, reason_code 写进审计。"""
        raise BridgeReject(403, ERR_ALLOWLIST, reason_code, "本次操作不在允许范围内，已拒绝")
