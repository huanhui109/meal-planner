"""T05：双向唤醒模块端点级集成回归（真 MySQL 命名库）。

必须标记 ``requires_mysql``：未设置 ``TEST_DATABASE_URL`` 时是 **skip 不是 pass**，
一条没跑过的断言等于没有断言。用既有 ``api_client`` / ``db_session`` / ``auth_headers``
fixture，不新建库、不改任何后端源码。

启用手段（不触发 lifespan）：
  - L0：测试内设 ``APP__INBOUND_BRIDGE__ENABLED=true`` 并 ``reset_settings_cache()``；
  - L1：往 ``inbound_bridge_config`` 写单行 ``id=1, enabled=1``；
  - 传输：设 ``APP__INBOUND_BRIDGE__TRANSPORT=poll``（M2 降级），这样唤醒不需要
    WorkBuddy OAuth 连接，助手回执直接走 ``POST /receipts``，正好是本模块要验的端点。

如实标注的边界：M2 模式不产生出站 WorkBuddy 消息，因此"出站 content 不含令牌"由
``backend/tests/unit/test_inbound_tokens.py`` 的 ``WakeOrchestrator._content`` 单测覆盖；
本文件只覆盖 HTTP 响应 / 审计表 / 库内字段的脱敏。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from app.config import reset_settings_cache
from app.models.inbound_bridge import (
    InboundAudit,
    InboundBridgeConfig,
    InboundTask,
    InboundTokenPair,
)
from app.models.meal import MealEvent, MealStockMovement
from app.services.inbound_bridge import ALLOWLIST_VERSION, AuditService
from app.services.inbound_bridge.tokens import TokenService
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql

SENSITIVE_PREFIXES = ("fd_ib_", "fd_skill_", "private-")


# ---------------------------------------------------------------- fixtures / 工具

@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """每个用例前后都清一次 settings 单例缓存，保证 L0 默认值不被上一个用例污染。"""
    reset_settings_cache()
    yield
    reset_settings_cache()


# InboundTask 已在模型层开启 eager_defaults（models/inbound_bridge.py）：
# INSERT 时由 flush() 直接取回 CURRENT_TIMESTAMP server_default，
# WakeOrchestrator.view() 不再触发隐式 SELECT / MissingGreenlet。
# 曾经的测试侧 ORM 补丁已删除，端点链路必须由生产源码本身真实跑通。
@pytest_asyncio.fixture
async def bridge_on(db_session):
    """打开 L0(环境) + L1(表)，并切到 M2 poll 传输，避免依赖 WorkBuddy OAuth。"""
    keys = {
        "APP__INBOUND_BRIDGE__ENABLED": "true",
        "APP__INBOUND_BRIDGE__TRANSPORT": "poll",
    }
    old = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    reset_settings_cache()
    db_session.add(InboundBridgeConfig(id=1, enabled=True, reason=None))
    await db_session.commit()
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_settings_cache()


def _sign(env: dict, plaintext: str) -> str:
    """用后端权威的 canonical + derive_key 两步 HMAC 构造合法签名。"""
    return hmac.new(
        TokenService.derive_key(plaintext),
        TokenService.canonical(env).encode(),
        hashlib.sha256,
    ).hexdigest()


def _envelope(pair, *, side, event_type, direction, phase, task_id="", data=None, **over):
    env = {
        "v": 1,
        "pair_id": pair["pair_id"],
        "direction": direction,
        "event_type": event_type,
        "event_id": str(uuid4()),
        "task_id": task_id,
        "phase": phase,
        "assistant_instance_id": pair["assistant_instance_id"],
        "session_id": pair["session_id"],
        "issued_at": int(time.time()),
        "nonce": str(uuid4()),
        "allowlist_version": ALLOWLIST_VERSION,
        "data": data if data is not None else {},
    }
    env.update(over)
    token = pair["web_token"] if side == "web" else pair["assistant_token"]
    env["sig"] = _sign(env, token)
    return env


async def _current(api_client, headers):
    response = await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _event_data(current, *, request_id=None, instruction="两个人，不开火，不辣"):
    """完整 MealContext + 与当前餐次一致的 revision，宽松条件保证候选非空。"""
    return {
        "request_id": request_id or str(uuid4()),
        "instruction": instruction,
        "context": {**current["context"], "max_minutes": 180, "avoid_recent": False},
        "expected_revision": current["revision"],
    }


async def _setup(db_session, api_client, auth_headers, *, open_id="ou_t05_main"):
    user = await make_user(db_session, open_id=open_id)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/inbound/bridge/pair", headers=headers)
    assert response.status_code == 200, response.text
    pair = response.json()["data"]
    return user, headers, pair, await _current(api_client, headers)


async def _post_event(api_client, headers, pair, data, **over):
    params = dict(
        side="web", event_type="meal.adjust.requested",
        direction="web_to_bridge", phase="-", data=data,
    )
    params.update(over)  # 允许覆盖 event_type / allowlist_version 等构造拒绝样本
    env = _envelope(pair, **params)
    return await api_client.post("/api/inbound/bridge/events", headers=headers, json=env)


def _no_leak(text: str) -> None:
    for prefix in SENSITIVE_PREFIXES:
        assert prefix not in text, f"响应/内容泄漏了敏感前缀 {prefix}"


# ---------------------------------------------------------------- 默认停用（L0/L1）

async def test_default_disabled_returns_503_and_legacy_paths_still_work(
    db_session, api_client, auth_headers,
):
    """L0 默认 false：新端点 503；既有旧桥 / 快速推荐 / Skill 连接 100% 可用。"""
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)

    response = await api_client.get("/api/inbound/bridge/allowlist", headers=headers)
    assert response.status_code == 503, response.text
    _no_leak(response.text)

    # 既有 /api/assistant/adjustments/current
    current = await _current(api_client, headers)
    legacy = await api_client.get(
        "/api/assistant/adjustments/current", headers=headers,
        params={"meal_slot": current["context"]["meal_slot"], "meal_date": current["context"]["meal_date"]},
    )
    assert legacy.status_code == 200, legacy.text

    # 快速推荐（走 propose 的 quick 分支，不依赖双向唤醒）
    quick = await api_client.post("/api/meals/propose", headers=headers, json={
        "context": {**current["context"], "max_minutes": 180, "avoid_recent": False},
        "expected_revision": current["revision"],
    })
    assert quick.status_code == 200, quick.text

    # Skill 连接凭据
    grant = await api_client.post("/api/assistant/grants", headers=headers, json={})
    assert grant.status_code == 200, grant.text
    assert grant.json()["data"]["token"].startswith("fd_skill_")


# ---------------------------------------------------------------- 令牌颁发

async def test_pair_issues_one_time_tokens_and_db_stores_no_plaintext(
    db_session, api_client, auth_headers, bridge_on,
):
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/inbound/bridge/pair", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["web_token"].startswith("fd_ib_web_")
    assert data["assistant_token"].startswith("fd_ib_asst_")
    assert data["web_state"] == "active" and data["assistant_state"] == "active"

    await db_session.rollback()
    rows = (await db_session.execute(select(InboundTokenPair))).scalars().all()
    assert len(rows) == 1
    blob = json.dumps(
        [{c.name: str(getattr(r, c.name)) for c in InboundTokenPair.__table__.columns} for r in rows],
        ensure_ascii=False,
    )
    assert "fd_ib_" not in blob  # 库内 grep 不到明文
    assert rows[0].web_token_hash == hashlib.sha256(data["web_token"].encode()).hexdigest()
    assert rows[0].assistant_token_hash == hashlib.sha256(data["assistant_token"].encode()).hexdigest()


# ---------------------------------------------------------------- 三级默认拒绝

async def test_events_default_deny_chain(db_session, api_client, auth_headers, bridge_on):
    """无认证 / 错签名 401、白名单外 403、版本不匹配 403、重放 event_id 401。"""
    _, headers, pair, current = await _setup(db_session, api_client, auth_headers)
    data = _event_data(current)

    # 无认证（等价于完全没有凭据的请求）-> 401
    bare = _envelope(pair, side="web", event_type="meal.adjust.requested",
                     direction="web_to_bridge", phase="-", data=data)
    no_auth = await api_client.post("/api/inbound/bridge/events", json=bare)
    assert no_auth.status_code == 401, no_auth.text
    _no_leak(no_auth.text)

    # 错签名 -> 401 bad_signature
    bad = dict(bare, event_id=str(uuid4()), nonce=str(uuid4()))
    bad["sig"] = "0" * 64
    bad_response = await api_client.post("/api/inbound/bridge/events", headers=headers, json=bad)
    assert bad_response.status_code == 401, bad_response.text

    # 白名单外：永久禁止清单 + P1 disabled，均 403
    for event_type in ("meal.accept", "order.create", "pair.status_queried"):
        denied = await _post_event(api_client, headers, pair, data, event_type=event_type)
        assert denied.status_code == 403, (event_type, denied.text)

    # 版本不匹配 -> 403
    version = await _post_event(api_client, headers, pair, data, allowlist_version="ib-0.9")
    assert version.status_code == 403, version.text

    # 重放：先成功一次，再原样重发同一 event_id -> 401 replay
    env = _envelope(pair, side="web", event_type="meal.adjust.requested",
                    direction="web_to_bridge", phase="-", data=data)
    first = await api_client.post("/api/inbound/bridge/events", headers=headers, json=env)
    assert first.status_code == 200, first.text
    replay = await api_client.post("/api/inbound/bridge/events", headers=headers, json=env)
    assert replay.status_code == 401, replay.text

    for response in (bad_response, version, replay):
        _no_leak(response.text)


# ---------------------------------------------------------------- 幂等 / 归属

async def test_idempotency_same_task_conflict_and_cross_user(
    db_session, api_client, auth_headers, bridge_on,
):
    """同一 request_id 返回同一任务；同 ID 不同参数 409；跨用户 404 等价。"""
    _, headers, pair, current = await _setup(db_session, api_client, auth_headers)
    request_id = str(uuid4())
    data = _event_data(current, request_id=request_id)

    first = await _post_event(api_client, headers, pair, data)
    assert first.status_code == 200, first.text
    task_id = first.json()["data"]["task_id"]
    assert task_id == request_id
    assert first.json()["data"]["status"] == "awaiting_assistant"  # M2 poll 态

    # 新 event_id、相同参数 -> 幂等返回同一任务，不重复建任务
    repeated = await _post_event(api_client, headers, pair, data)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["task_id"] == task_id

    # 同一 request_id 不同 instruction -> 409
    conflict = await _post_event(api_client, headers, pair, _event_data(
        current, request_id=request_id, instruction="换成完全不同的另一个要求",
    ))
    assert conflict.status_code == 409, conflict.text

    # 跨用户用同一 request_id -> 404 等价
    other = await make_user(db_session, open_id="ou_t05_other")
    await db_session.commit()
    other_headers = auth_headers(other.id)
    other_pair = (await api_client.post("/api/inbound/bridge/pair", headers=other_headers)).json()["data"]
    crossed = await _post_event(api_client, other_headers, other_pair, _event_data(current, request_id=request_id))
    assert crossed.status_code == 404, crossed.text

    # /status 归属隔离
    assert (await api_client.get(
        "/api/inbound/bridge/status", headers=headers, params={"task_id": task_id},
    )).status_code == 200
    assert (await api_client.get(
        "/api/inbound/bridge/status", headers=other_headers, params={"task_id": task_id},
    )).status_code == 404


# ---------------------------------------------------------------- 回执四元匹配 / 0 propose

async def test_receipts_ignored_mismatch_and_failure_never_propose(
    db_session, api_client, auth_headers, bridge_on,
):
    """四元不匹配被忽略、异常分支 0 次 propose，current_proposal_id / revision 不变。"""
    _, headers, pair, current = await _setup(db_session, api_client, auth_headers)
    data = _event_data(current)
    started = await _post_event(api_client, headers, pair, data)
    assert started.status_code == 200, started.text
    task_id = started.json()["data"]["task_id"]

    before = await _current(api_client, headers)
    assert before["revision"] == 0 and before["proposal"] is None

    # assistant.failed 允许 context 与 proposal 两个阶段：阶段不匹配时网关放行，
    # 但 ReceiptValidator 的四元匹配判为 ignored，不建方案。
    mismatch = _envelope(
        pair, side="assistant", event_type="assistant.failed",
        direction="assistant_to_bridge", phase="proposal", task_id=task_id,
        data={"request_id": task_id, "phase": "proposal", "error": "不匹配回执"},
    )
    ignored = await api_client.post("/api/inbound/bridge/receipts", json=mismatch)
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["data"]["status"] == "awaiting_assistant"  # 原任务没被改动

    # 阶段匹配的失败回执 -> task failed，同样 0 次 propose
    failed = _envelope(
        pair, side="assistant", event_type="assistant.failed",
        direction="assistant_to_bridge", phase="context", task_id=task_id,
        data={"request_id": task_id, "phase": "context", "error": "助手无法满足"},
    )
    failed_response = await api_client.post("/api/inbound/bridge/receipts", json=failed)
    assert failed_response.status_code == 200, failed_response.text
    assert failed_response.json()["data"]["status"] == "failed"

    after = await _current(api_client, headers)
    assert after["revision"] == before["revision"]  # 0 次 propose，revision 不变
    assert after["proposal"] is None  # current_proposal_id 未变
    assert (await db_session.execute(select(MealStockMovement))).scalars().all() == []


# ---------------------------------------------------------------- 正常链路

async def test_full_roundtrip_proposes_once_without_side_effects(
    db_session, api_client, auth_headers, bridge_on,
):
    """两阶段回执完成后 source=assistant / status=proposed / revision+1，无库存与 eaten。"""
    _, headers, pair, current = await _setup(db_session, api_client, auth_headers)
    data = _event_data(current)
    started = await _post_event(api_client, headers, pair, data)
    assert started.status_code == 200, started.text
    task_id = started.json()["data"]["task_id"]
    assert started.json()["data"]["phase"] == "context"

    # 第一阶段：条件补丁（空补丁，不改日期/餐次/忌口）-> 进入 proposal
    context_reply = _envelope(
        pair, side="assistant", event_type="assistant.context_replied",
        direction="assistant_to_bridge", phase="context", task_id=task_id,
        data={"request_id": task_id, "phase": "context", "context": {}},
    )
    stage2 = await api_client.post("/api/inbound/bridge/receipts", json=context_reply)
    assert stage2.status_code == 200, stage2.text
    assert stage2.json()["data"]["phase"] == "proposal"

    # 从库里取服务端二次校验后真实提供的候选 key（绝不杜撰）
    await db_session.rollback()
    row = (await db_session.execute(
        select(InboundTask).where(InboundTask.id == task_id)
    )).scalar_one()
    candidates = row.payload.get("candidates") or []
    assert candidates, "第一阶段没有产出候选，无法继续"
    complete = next((c for c in candidates if c["role"] == "complete"), None)
    if complete is not None:
        keys = [complete["key"]]  # servings=1 时一份完整主食餐即合法
    else:
        main = next(c for c in candidates if c["role"] == "main")
        side = next(c for c in candidates if c["role"] == "side")
        staple = next(c for c in candidates if c["role"] == "staple")
        keys = [main["key"], side["key"], staple["key"]]

    # 第二阶段：真实候选 key 组合 -> 唯一写入口 propose
    proposal_reply = _envelope(
        pair, side="assistant", event_type="assistant.proposal_replied",
        direction="assistant_to_bridge", phase="proposal", task_id=task_id,
        data={"request_id": task_id, "phase": "proposal", "candidate_keys": keys,
              "reason": "按两人不开火不辣的要求搭配"},
    )
    done = await api_client.post("/api/inbound/bridge/receipts", json=proposal_reply)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["status"] == "proposed", done.text

    latest = await _current(api_client, headers)
    assert latest["revision"] == 1  # 由 0 -> 1
    assert latest["proposal"]["source"] == "assistant"
    assert latest["proposal"]["status"] == "proposed"
    assert (await db_session.execute(select(MealStockMovement))).scalars().all() == []
    kinds = (await db_session.execute(select(MealEvent.kind))).scalars().all()
    assert "accepted" not in kinds and "eaten" not in kinds

    # 响应 / 日志载体（HTTP 响应）均不含令牌前缀
    for response in (started, stage2, done):
        _no_leak(response.text)


# ---------------------------------------------------------------- 枚举 / 生命周期 / 审计 / 脱敏

async def test_enumeration_lifecycle_poll_and_no_token_leak(
    db_session, api_client, auth_headers, bridge_on,
):
    """其余端点可用、路径与 SAFE_FIELDS 一致、令牌不进任何非 /pair 响应或审计表。"""
    _, headers, pair, current = await _setup(db_session, api_client, auth_headers)
    data = _event_data(current)
    started = await _post_event(api_client, headers, pair, data)
    assert started.status_code == 200, started.text
    task_id = started.json()["data"]["task_id"]

    allowlist = await api_client.get("/api/inbound/bridge/allowlist", headers=headers)
    assert allowlist.status_code == 200, allowlist.text
    assert allowlist.json()["data"]["version"] == "ib-1.0"
    assert len(allowlist.json()["data"]["events"]) == 9

    status = await api_client.get(
        "/api/inbound/bridge/status", headers=headers, params={"task_id": task_id},
    )
    assert status.status_code == 200 and status.json()["data"]["task_id"] == task_id

    # GET /poll：助手侧签名信封放 X-Inbound-Envelope 头，不进 URL
    poll_env = _envelope(
        pair, side="assistant", event_type="task.status_queried",
        direction="assistant_to_bridge", phase="-", data={},
    )
    poll = await api_client.get("/api/inbound/bridge/poll", headers={
        "X-Inbound-Envelope": json.dumps(poll_env, ensure_ascii=False, separators=(",", ":")),
    })
    assert poll.status_code == 200, poll.text
    assert poll.json()["data"]["version"] == "ib-1.0"
    assert "fd_ib_" not in str(poll.request.url)  # 令牌没进 URL

    # 单端轮换 / 撤销
    rotated = await api_client.post(
        f"/api/inbound/bridge/pair/{pair['pair_id']}/rotate", headers=headers, params={"side": "web"},
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["data"]["token"].startswith("fd_ib_web_")
    revoked = await api_client.delete(
        f"/api/inbound/bridge/pair/{pair['pair_id']}", headers=headers, params={"side": "assistant"},
    )
    assert revoked.status_code == 200, revoked.text

    audit = await api_client.get("/api/inbound/bridge/audit", headers=headers, params={"limit": 50})
    assert audit.status_code == 200, audit.text
    rows = audit.json()["data"]
    assert isinstance(rows, list) and rows
    for item in rows:
        assert set(item) == set(AuditService.SAFE_FIELDS)

    # 库内审计表也不含任何令牌明文
    await db_session.rollback()
    audit_rows = (await db_session.execute(select(InboundAudit))).scalars().all()
    blob = json.dumps(
        [{c.name: str(getattr(r, c.name)) for c in InboundAudit.__table__.columns} for r in audit_rows],
        ensure_ascii=False,
    )
    assert "fd_ib_" not in blob and "fd_skill_" not in blob and "private-" not in blob

    # 除 /pair 一次性展示外，所有响应都不含令牌前缀
    for response in (allowlist, status, poll, revoked, audit):
        _no_leak(response.text)
