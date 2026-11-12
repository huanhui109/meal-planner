"""回执校验与兼容别名写入口。

四元匹配 (令牌 + 事件类型 + task_id + phase)、服务端二次校验、两阶段幂等:
- context 阶段: 条件补丁复核 (日期餐次不变 / 忌口不放宽 / None 不合法) ->
  MealService.assistant_context() 重算候选 (每角色最多 24) -> 进入 proposal 并触发第二轮唤醒。
- proposal 阶段: candidate_keys 必须属于 payload.candidate_keys -> 同事务调用
  MealService.propose() -> status=proposed。

兼容别名（deprecated）：统一模式的主链路是 ``/api/assistant/adjustments*``，
由 ``AssistantAdjustmentService.commit()`` 直接发起模型请求并写入方案。本模块
保留九端点的既有外契约，但方案写入已 **委托** 给统一核心的
``AssistantAdjustmentService.propose_for_compat()``，全应用只有一处真正调用
``MealService.propose()``。任何异常分支 propose 调用次数为 0，原方案不变；
proposed 之后绝不自动 accept。
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbound_bridge import InboundTask
from app.schemas.inbound_bridge import (
    ContextReplyData,
    FailureReplyData,
    InboundEnvelope,
    ProposalReplyData,
)
from app.schemas.meal import MealContext, MealContextPatch
from app.services.meal_service import MealService

from . import ACTIVE_TASK_STATUSES, ERR_SCHEMA, BridgeReject, scrub

_CANDIDATE_FIELDS = (
    "key", "name", "role", "ingredients", "estimated_minutes",
    "estimated_cost", "spice",
)


class ReceiptValidator:
    def __init__(self, db: AsyncSession, meals: MealService):
        self.db = db
        self.meals = meals

    # ---------------------------------------------------------------- 四元匹配

    async def validate(self, envelope: InboundEnvelope, task: InboundTask) -> dict:
        """四元匹配 + 任务在途 + schema 校验。失败/迟到一律 ignored, 0 次 propose。"""
        if envelope.task_id != task.id or envelope.phase != task.phase:
            return {"status": "ignored"}
        if (
            envelope.assistant_instance_id != task.assistant_instance_id
            or envelope.session_id != task.session_id
        ):
            return {"status": "ignored"}

        event = envelope.event_type
        if event == "assistant.failed":
            expected_phases = ("context", "proposal")
        elif event == "assistant.context_replied":
            expected_phases = ("context",)
        elif event == "assistant.proposal_replied":
            expected_phases = ("proposal",)
        else:
            return {"status": "ignored"}
        if task.phase not in expected_phases:
            return {"status": "ignored"}

        # 取消 / 断开 / 超时后的迟到回执: 任务已不在途, 直接忽略不落库。
        if task.status not in ACTIVE_TASK_STATUSES:
            return {"status": "ignored"}

        try:
            if event == "assistant.failed":
                reply = FailureReplyData.model_validate(envelope.data)
            elif event == "assistant.context_replied":
                reply = ContextReplyData.model_validate(envelope.data)
            else:
                reply = ProposalReplyData.model_validate(envelope.data)
        except ValidationError:
            raise BridgeReject(422, ERR_SCHEMA, "schema_invalid", "助手回执格式不正确") from None

        if event == "assistant.failed":
            task.status = "failed"
            task.error = scrub(reply.error)[:500]
            await self.db.commit()
            return {"status": "failed"}

        task.status = "validating"
        await self.db.flush()
        return {"status": "ok", "reply": reply, "event_type": event, "phase": task.phase}

    # ---------------------------------------------------------------- 唯一写入口

    async def commit(self, task: InboundTask, proposal_reply) -> dict:
        """唯一可调用 MealService.propose() 的位置。"""
        # 重复轮询幂等: 已 proposed 的任务不得再产生第二份方案。
        if task.status == "proposed":
            return {"status": "proposed", "proposal_id": task.proposal_id, "wake": False}

        if isinstance(proposal_reply, FailureReplyData):
            task.status = "failed"
            task.error = scrub(proposal_reply.error)[:500]
            await self.db.commit()
            return {"status": "failed", "wake": False}
        if isinstance(proposal_reply, ContextReplyData):
            return await self._commit_context(task, proposal_reply)
        if isinstance(proposal_reply, ProposalReplyData):
            return await self._commit_proposal(task, proposal_reply)

        # 未识别的回执: 收敛到 failed, 绝不 propose。
        task.status = "failed"
        task.error = "助手回执类型无法识别，原方案未改变"
        await self.db.commit()
        return {"status": "failed", "wake": False}

    async def _commit_context(self, task: InboundTask, reply: ContextReplyData) -> dict:
        """阶段一: 条件补丁复核 -> 重算候选 -> 进入 proposal, 返回 wake=True 触发第二轮唤醒。"""
        changes = reply.context.model_dump(mode="json", exclude_unset=True)
        if any(value is None and key != "budget" for key, value in changes.items()):
            return await self._fail(task, "助手返回了不完整的用餐条件，原方案未改变")
        try:
            target = MealContext.model_validate({**task.context, **changes})
        except ValidationError:
            return await self._fail(task, "助手返回了不合法的用餐条件，原方案未改变")

        # 日期 / 餐次不可改; 忌口不放宽 (已保存项不可删、素食/清淡不可从 True 变 False)。
        if (
            target.meal_date.isoformat() != task.context.get("meal_date")
            or target.meal_slot != task.context.get("meal_slot")
        ):
            return await self._fail(task, "请先在网页切换日期或餐次，再发送调整要求；原方案未改变")
        old_avoid = set(task.context.get("avoid") or [])
        if (
            old_avoid - set(target.avoid)
            or (task.context.get("vegetarian") and not target.vegetarian)
            or (task.context.get("light") and not target.light)
        ):
            return await self._fail(task, "已保存的忌口不会被自动放宽，原方案未改变")

        data = await self.meals.assistant_context(
            task.user_id, MealContextPatch.model_validate(target.model_dump(mode="json"))
        )
        if data["revision"] != task.expected_revision:
            task.status = "conflict"
            task.error = "这一餐已在另一处更新，已保留最新方案，请重新发送调整"
            await self.db.commit()
            return {"status": "conflict", "wake": False}
        if not data["candidates"]:
            return await self._fail(task, "这些条件下没有合适候选，忌口不会被自动放宽")

        # 平衡角色并去掉执行细节, 每角色最多 24, 让大菜谱库能塞进一次助手回合。
        counts: dict[str, int] = {}
        candidates = []
        for dish in sorted(data["candidates"], key=lambda d: d.get("estimated_minutes") or 0):
            role = dish.get("role", "")
            if counts.get(role, 0) >= 24:
                continue
            counts[role] = counts.get(role, 0) + 1
            candidates.append({field: dish.get(field) for field in _CANDIDATE_FIELDS})

        task.payload = {
            **(task.payload or {}),
            "context": data["context"],
            "candidate_keys": [dish["key"] for dish in candidates],
            "candidates": candidates,
            "protected_avoid": data["protected_avoid"],
        }
        task.phase = "proposal"
        task.status = "waking"
        task.message_id = None
        task.error = None
        await self.db.commit()
        # API 见到 wake=True 后调用 orchestrator.wake(task) 触发第二轮 (wake 不 propose)。
        return {"status": "waking", "phase": "proposal", "wake": True}

    async def _commit_proposal(self, task: InboundTask, reply: ProposalReplyData) -> dict:
        """阶段二: 二次校验通过后, 委托统一核心写入方案并置 proposed。

        兼容别名：九端点仍维护自己的 ``InboundTask`` 行，但真正的
        ``MealService.propose()`` 只由 ``AssistantAdjustmentService`` 调用一次，
        保证全应用单一方案写入口。
        """
        from app.services.assistant_adjustment_service import AssistantAdjustmentService

        allowed = set((task.payload or {}).get("candidate_keys") or [])
        if not set(reply.candidate_keys) <= allowed:
            # 0 次 propose, 原方案不变。
            return await self._fail(task, "助手选择了未提供的候选，原方案未改变")

        try:
            patch = MealContextPatch.model_validate((task.payload or {}).get("context") or {})
            # 第 3/4 步之间服务端二次校验最终由 propose() 的 check_revision() 兜底;
            # propose 结果与 status=proposed 同事务提交, 重复轮询不产生第二份方案。
            result = await AssistantAdjustmentService(self.db).propose_for_compat(
                task.user_id, patch, task.expected_revision, reply.candidate_keys, reply.reason,
            )
            task.proposal_id = result["proposal"]["id"]
            task.status = "proposed"
            await self.db.flush()
        except HTTPException as exc:
            # 409 revision 冲突 / 422 校验失败: 原写入回滚, 0 次 propose, 原方案不变。
            task.status = "conflict" if exc.status_code == 409 else "failed"
            task.error = scrub(str(exc.detail))[:500]
            await self.db.commit()
            return {"status": task.status, "wake": False}
        except ValidationError:
            return await self._fail(task, "助手回执数据不合法，原方案未改变")

        await self.db.commit()
        return {"status": "proposed", "proposal_id": task.proposal_id, "wake": False}

    async def _fail(self, task: InboundTask, message: str) -> dict:
        task.status = "failed"
        task.error = scrub(message)[:500]
        await self.db.commit()
        return {"status": "failed", "wake": False}
