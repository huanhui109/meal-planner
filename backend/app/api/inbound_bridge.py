"""双向唤醒模块 API - 兼容别名 router, 九端点。

兼容别名（deprecated）：统一模式由 ``/api/assistant/adjustments*`` 在应用内
直接发起模型请求并写入方案；本九端点完整保留既有外契约（路径 / 鉴权 / L0-L1 /
签名 / 审计 / 白名单），内部方案写入已委托统一核心
``AssistantAdjustmentService.propose_for_compat()``，不再产生第二套主状态机。

所有响应统一 SuccessResponse{code,data,message}; 错误由 problem() 抛 HTTPException,
对外只给可读中文文案, 内部细节与令牌一律 scrub 后不进响应。全部端点 no_store。

鉴权分两类:
- 网页侧 (get_current_user + 网页侧令牌签名): /events /status /pair /rotate /delete
  /allowlist /audit
- 助手侧 (不依赖网页 JWT, 靠助手侧令牌签名): /receipts /poll
  /poll 是 GET 无请求体, envelope 放在 X-Inbound-Envelope 请求头 (JSON 字符串)。

默认拒绝三级链由 InboundGateway.admit 承担; 归属隔离、幂等、四元匹配、revision/eaten
复核在端点与 ReceiptValidator 完成。端点不直接写方案、不调 propose。
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.dependencies import get_current_user, get_db
from app.models.inbound_bridge import InboundTask
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.inbound_bridge import AdjustRequestedData, CancelData, InboundEnvelope
from app.schemas.meal import MealContextPatch
from app.services.inbound_bridge import (
    ACTIVE_TASK_STATUSES,
    ALLOWLIST_VERSION,
    DIRECTIONS,
    PHASES,
    SIDES,
    AllowlistRegistry,
    AuditService,
    BridgeReject,
    BridgeSwitch,
    InboundGateway,
    ReceiptValidator,
    TokenService,
    WakeOrchestrator,
    scrub,
)
from app.services.meal_service import MealService, meal_now, problem
from app.services.workbuddy_client import WorkBuddyClient, get_workbuddy_client
from app.services.workbuddy_service import WorkBuddyService


def no_store(response: Response) -> None:
    """与 api/assistant.py:24-28 同构, 全部端点挂 Cache-Control: no-store。"""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/inbound/bridge", tags=["双向唤醒"], dependencies=[Depends(no_store)])

_WEB_EVENTS = ("meal.adjust.requested", "meal.adjust.cancelled", "meal.adjust.status_queried")


# ---------------------------------------------------------------- 依赖与辅助

def _services(db: AsyncSession, client: WorkBuddyClient) -> SimpleNamespace:
    """按请求装配全部服务对象 (共享同一个 db session)。"""
    settings: Settings = get_settings()
    tokens = TokenService(db, settings)
    allowlist = AllowlistRegistry()
    audit = AuditService(db)
    switch = BridgeSwitch(db, settings)
    gateway = InboundGateway(db, tokens, allowlist, audit, switch)
    host = WorkBuddyService(db, client)
    meals = MealService(db)
    orchestrator = WakeOrchestrator(db, client, host, tokens, settings)
    validator = ReceiptValidator(db, meals)
    return SimpleNamespace(
        db=db,
        settings=settings,
        tokens=tokens,
        allowlist=allowlist,
        audit=audit,
        switch=switch,
        gateway=gateway,
        host=host,
        meals=meals,
        orchestrator=orchestrator,
        validator=validator,
    )


async def _ensure_enabled(svc: SimpleNamespace) -> None:
    """不经过 admit 的端点也需要 L0/L1 短路。"""
    if not await svc.switch.enabled():
        problem(503, "双向唤醒模块已停用")


async def _admit(svc: SimpleNamespace, envelope: InboundEnvelope, side: str, user) -> tuple:
    """走网关三级默认拒绝, 返回 (pair, envelope)。BridgeReject 由端点统一转换。"""
    return await svc.gateway.admit(envelope, side, user)


def _header_envelope(request: Request) -> InboundEnvelope:
    """GET /poll 的助手侧签名信封放在 X-Inbound-Envelope 请求头, 不进 URL 查询串。"""
    raw = request.headers.get("X-Inbound-Envelope", "")
    if not raw:
        problem(422, "请求格式不正确")
    try:
        return InboundEnvelope.model_validate_json(raw)
    except (ValidationError, ValueError):
        problem(422, "请求格式不正确")


def _reject(rej: BridgeReject) -> None:
    problem(rej.status, scrub(rej.message))


async def _record(svc, envelope, user_id: int, outcome: str, reason: str, *, commit: bool) -> None:
    """把本次请求的最终结论写进审计 (占位行由 consume_event_id 预置)。

    重放不记审计, 保护原始记录。commit=True 用于会被 get_db 回滚的拒绝分支。
    """
    if reason == "replay":
        return
    try:
        await svc.audit.record(envelope.event_id, user_id, outcome, reason, envelope)
        if commit:
            await svc.db.commit()
    except Exception:  # noqa: BLE001 - 审计失败绝不影响主流程结论
        pass


async def _business_reject(svc, envelope, user_id, reason: str, status: int, message: str) -> None:
    """三级业务校验失败: 记 rejected 审计并独立提交, 再抛可读中文错误。"""
    await _record(svc, envelope, user_id, "rejected", reason, commit=True)
    problem(status, message)


# ---------------------------------------------------------------- 网页触发

@router.post("/events", response_model=SuccessResponse)
async def post_events(
    payload: InboundEnvelope,
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """只接 requested / cancelled / status_queried; requested 建任务并唤醒。"""
    svc = _services(db, client)
    try:
        pair, env = await _admit(svc, payload, "web", user)
        if env.event_type not in _WEB_EVENTS:
            await _business_reject(svc, env, user.id, "not_allowlisted", 403, "本次操作不在允许范围内，已拒绝")

        if env.event_type in ("meal.adjust.cancelled", "meal.adjust.status_queried"):
            ref = CancelData.model_validate(env.data)
            task = await db.get(InboundTask, str(ref.task_id))
            if task is None or task.user_id != user.id:
                await _business_reject(svc, env, user.id, "not_found", 404, "找不到这次调整")
            if env.event_type == "meal.adjust.cancelled":
                await svc.orchestrator.cancel(task, "已取消等待，本次回复不会保存")
            # status_queried: 只查询, 不重发。
            await db.commit()
            await _record(svc, env, pair.user_id, "allowed", "allowed", commit=True)
            return SuccessResponse(data=svc.orchestrator.view(task))

        data = AdjustRequestedData.model_validate(env.data)
        patch = MealContextPatch.model_validate(data.context.model_dump(mode="json"))
        view = await svc.meals.current(user.id, patch)
        if data.expected_revision != view["revision"]:
            await _business_reject(svc, env, user.id, "revision_conflict", 409, "这一餐已更新，请刷新后再发送")
        if view["proposal"] and view["proposal"]["status"] == "eaten":
            await _business_reject(svc, env, user.id, "eaten", 409, "这一餐已吃过，请先撤销记录再调整")

        # 幂等: 同一 request_id 已存在 -> 跨用户 404 / 参数不同 409 / 相同返回现有任务。
        existing = await db.get(InboundTask, str(data.request_id))
        if existing is not None:
            if existing.user_id != user.id:
                await _business_reject(svc, env, user.id, "cross_user", 404, "找不到这次调整")
            if (
                existing.instruction != data.instruction
                or existing.context != data.context.model_dump(mode="json")
                or existing.expected_revision != data.expected_revision
            ):
                await _business_reject(svc, env, user.id, "idempotency_conflict", 409, "同一请求编号不能用于不同调整，请重新发送")
            await _record(svc, env, pair.user_id, "allowed", "allowed", commit=True)
            return SuccessResponse(data=svc.orchestrator.view(existing))

        # 同用户仅一个在途任务; 过期的在途任务先收敛到 timed_out。
        active = (await db.execute(
            select(InboundTask).where(
                InboundTask.user_id == user.id,
                InboundTask.status.in_(ACTIVE_TASK_STATUSES),
            )
        )).scalars().all()
        for other in active:
            if other.expires_at > meal_now():
                await _business_reject(svc, env, user.id, "concurrent_task", 409, "已有一项调整正在处理，请等待或取消后再发送")
            other.status = "timed_out"
            other.error = "等待助手超时，原方案未改变"

        now = meal_now()
        cfg = svc.settings.inbound_bridge
        task = InboundTask(
            id=str(data.request_id),
            user_id=user.id,
            pair_id=pair.id,
            session_id=env.session_id,
            assistant_instance_id=env.assistant_instance_id,
            event_type=env.event_type,
            allowlist_version=env.allowlist_version,
            instruction=data.instruction,
            context=data.context.model_dump(mode="json"),
            expected_revision=data.expected_revision,
            phase="context",
            status="received",
            payload={},
            expires_at=now + timedelta(seconds=cfg.task_timeout_seconds),
            next_poll_at=now + timedelta(seconds=cfg.poll_seconds),
            poll_failures=0,
        )
        db.add(task)
        await db.flush()
        await svc.orchestrator.wake(task)
        await _record(svc, env, pair.user_id, "allowed", "allowed", commit=True)
        return SuccessResponse(data=svc.orchestrator.view(task))
    except BridgeReject as rej:
        await _record(svc, payload, user.id, "rejected", rej.reason_code, commit=True)
        _reject(rej)
    except ValidationError:
        await _record(svc, payload, user.id, "rejected", "schema_invalid", commit=True)
        problem(422, "请求数据格式不正确")


# ---------------------------------------------------------------- 助手回执

@router.post("/receipts", response_model=SuccessResponse)
async def post_receipts(
    payload: InboundEnvelope,
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    """不依赖网页 JWT, 靠助手侧签名; 四元匹配 -> validate/commit。"""
    svc = _services(db, client)
    try:
        pair, env = await _admit(svc, payload, "assistant", None)
        task = await db.get(InboundTask, env.task_id)
        if task is None or task.user_id != pair.user_id:
            await _business_reject(svc, env, pair.user_id, "not_found", 404, "找不到这次调整")
        result = await svc.validator.validate(env, task)
        if result["status"] == "ok":
            committed = await svc.validator.commit(task, result["reply"])
            if committed.get("wake"):
                # context -> proposal 阶段切换, 由编排触发第二轮唤醒 (不 propose)。
                await svc.orchestrator.wake(task)
        await db.commit()
        await _record(svc, env, pair.user_id, "allowed", "allowed", commit=True)
        return SuccessResponse(data=svc.orchestrator.view(task))
    except BridgeReject as rej:
        await _record(svc, payload, 0, "rejected", rej.reason_code, commit=True)
        _reject(rej)
    except ValidationError:
        await _record(svc, payload, 0, "rejected", "schema_invalid", commit=True)
        problem(422, "请求数据格式不正确")


# ---------------------------------------------------------------- 状态查询

@router.get("/status", response_model=SuccessResponse)
async def get_status(
    task_id: str = Query(..., min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """只查询不重发; 归属隔离, 跨用户 404 等价。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    task = await db.get(InboundTask, task_id)
    if task is None or task.user_id != user.id:
        problem(404, "找不到这次调整")
    return SuccessResponse(data=svc.orchestrator.view(task))


# ---------------------------------------------------------------- M2 降级拉取

@router.get("/poll", response_model=SuccessResponse)
async def get_poll(
    envelope: InboundEnvelope = Depends(_header_envelope),
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    """助手侧签名拉取在途任务。

    依 §6.7 时序, 拉取只做身份验签 (不建任务、不写方案), 因此这里直接
    tokens.verify 而不经过白名单 check —— 拉取用的 event_type 是 P1 登记但默认
    disabled 的 task.status_queried, 不会因此被误当成"放行了一个业务事件"。
    """
    svc = _services(db, client)
    await _ensure_enabled(svc)
    try:
        pair = await svc.tokens.verify(envelope, "assistant", None)
    except BridgeReject as rej:
        await _record(svc, envelope, 0, "rejected", rej.reason_code, commit=True)
        _reject(rej)
    await _record(svc, envelope, pair.user_id, "allowed", "poll", commit=False)
    tasks = await svc.orchestrator.pull_pending(pair.id)
    await db.commit()
    return SuccessResponse(data={"tasks": tasks, "version": ALLOWLIST_VERSION})


# ---------------------------------------------------------------- 令牌生命周期

@router.post("/pair", response_model=SuccessResponse)
async def post_pair(
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """颁发令牌对, 明文只在本次响应里出现一次。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    try:
        result = await svc.tokens.issue_pair(user.id)
        await db.commit()
        return SuccessResponse(data=result)
    except BridgeReject as rej:
        _reject(rej)


@router.post("/pair/{pair_id}/rotate", response_model=SuccessResponse)
async def rotate_pair(
    pair_id: str,
    side: str = Query(default="web"),
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """单端轮换; 归属不符 404 等价, 不影响另一端。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    if side not in SIDES:
        problem(422, "参数 side 必须是 web 或 assistant")
    try:
        pair = await svc.tokens.resolve(pair_id)
        if pair is None or pair.user_id != user.id:
            problem(404, "找不到这个连接")
        result = await svc.tokens.rotate(pair_id, side)
        await db.commit()
        return SuccessResponse(data=result)
    except BridgeReject as rej:
        _reject(rej)


@router.delete("/pair/{pair_id}", response_model=SuccessResponse)
async def revoke_pair(
    pair_id: str,
    side: str = Query(default="web"),
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """单端撤销; 归属不符 404 等价, 另一端仍 active。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    if side not in SIDES:
        problem(422, "参数 side 必须是 web 或 assistant")
    try:
        pair = await svc.tokens.resolve(pair_id)
        if pair is None or pair.user_id != user.id:
            problem(404, "找不到这个连接")
        await svc.tokens.revoke(pair_id, side)
        await db.commit()
        return SuccessResponse(data={"revoked": True})
    except BridgeReject as rej:
        _reject(rej)


# ---------------------------------------------------------------- 枚举与审计

@router.get("/allowlist", response_model=SuccessResponse)
async def get_allowlist(
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """枚举白名单 + 版本 + 方向 + 阶段 + enabled。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    return SuccessResponse(data={
        "version": svc.allowlist.VERSION,
        "events": svc.allowlist.enumerate(),
        "forbidden": sorted(svc.allowlist.FROZEN_FORBIDDEN),
        "directions": list(DIRECTIONS),
        "phases": list(PHASES),
        "enabled": True,
    })


@router.get("/audit", response_model=SuccessResponse)
async def get_audit(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    user: User = Depends(get_current_user),
):
    """仅返回自己的审计记录 (SAFE_FIELDS)。"""
    svc = _services(db, client)
    await _ensure_enabled(svc)
    rows = await svc.audit.list_for_user(user.id, limit)
    return SuccessResponse(data=rows)
