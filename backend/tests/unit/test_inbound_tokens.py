"""T05：双向唤醒信任中心单测 —— 纯逻辑 + aiosqlite 轻量 DB。

不依赖 MySQL，也不被 ``requires_mysql`` 跳过：直接用 aiosqlite 内存库**只建 4 张新表**
（InboundTokenPair / InboundTask / InboundAudit / InboundBridgeConfig），刻意不调用
``Base.metadata.create_all``，避免把 MySQL 专有类型、user 表外键与既有 15 张表拖进来。

跨语言固定向量说明：本文件的向量是用 Python 后端 ``TokenService.canonical`` +
``derive_key`` 重新算出来的，与 ``frontend/tests/inbound-bridge.test.ts`` 里的同一个向量
双向钉住。**没有硬抄任务描述里 T04 的 data_hash / sig** —— 那对应的是另一份 envelope，
字段不同 sig 必然不同（任务里已经明确提醒过）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app.config import Settings
from app.models.inbound_bridge import (
    InboundAudit,
    InboundBridgeConfig,
    InboundTask,
    InboundTokenPair,
)
from app.schemas.inbound_bridge import InboundEnvelope
from app.services.inbound_bridge import (
    ALLOWLIST_VERSION,
    ERR_ALLOWLIST,
    ERR_NOT_FOUND,
    ERR_TOKEN,
    BridgeReject,
    WakeOrchestrator,
    placeholder_id,
    scrub,
)
from app.services.inbound_bridge.tokens import TokenService
from app.services.meal_service import meal_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------- 跨语言固定向量
# 由下方 fixed vector 的 envelope 字段经后端真实函数算出，前后端测试共用同一组常量。
PLAINTEXT = "fd_ib_web_TEST_VECTOR_TOKEN_0123456789abcdef"
ASST_PLAINTEXT = "fd_ib_asst_TEST_VECTOR_TOKEN_0123456789abcdef"
FIXED_PAIR_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
FIXED_INSTANCE_ID = "11111111-2222-4333-8444-555555555555"
FIXED_SESSION_ID = "66666666-7777-4888-8999-000000000000"
FIXED_EVENT_ID = "abcdefab-1234-4567-8abc-1234567890ab"
FIXED_NONCE = "fandecide-t05-regression-nonce"
FIXED_ISSUED_AT = 1762329600
FIXED_DATA = {
    "context": {
        "avoid": ["香菜", "花生"],
        "meal_date": "2026-11-05",
        "meal_slot": "dinner",
        "mode": "takeout",
        "servings": 2,
        "max_minutes": 30,
        "budget": None,
        "max_spice": 2,
        "vegetarian": False,
        "light": False,
        "use_fridge": True,
        "avoid_recent": True,
    },
    "expected_revision": 7,
    "instruction": "今晚两个人，不想开火，清淡一点「别太辣」",
    "request_id": "11111111-2222-3333-4444-555555555555",
}
# Python 后端 json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
FIXED_STABLE = (
    '{"context":{"avoid":["香菜","花生"],"avoid_recent":true,"budget":null,'
    '"light":false,"max_minutes":30,"max_spice":2,"meal_date":"2026-11-05",'
    '"meal_slot":"dinner","mode":"takeout","servings":2,"use_fridge":true,'
    '"vegetarian":false},"expected_revision":7,'
    '"instruction":"今晚两个人，不想开火，清淡一点「别太辣」",'
    '"request_id":"11111111-2222-3333-4444-555555555555"}'
)
FIXED_DATA_HASH = "b803bab3a1ecd362b30a52fd4cd7bf26593d89a67924bc754e2e2934d11e379a"
FIXED_CANONICAL = (
    "1\n"
    "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee\n"
    "web_to_bridge\n"
    "meal.adjust.requested\n"
    "\n"  # task_id 为空
    "-\n"
    "11111111-2222-4333-8444-555555555555\n"
    "66666666-7777-4888-8999-000000000000\n"
    "abcdefab-1234-4567-8abc-1234567890ab\n"
    "1762329600\n"
    "fandecide-t05-regression-nonce\n"
    "ib-1.0\n"
    "b803bab3a1ecd362b30a52fd4cd7bf26593d89a67924bc754e2e2934d11e379a"
)
FIXED_SIGNING_KEY_HEX = "caffe5b7bd03162de3706df34e6faa3f13a9edce30205e279c495def0b75212b"
FIXED_SIG = "864b2c9726de429e392f4678c44df3fff9030d1d25a47588d5532973c1d156b0"

FIXED_ENVELOPE = {
    "v": 1,
    "pair_id": FIXED_PAIR_ID,
    "direction": "web_to_bridge",
    "event_type": "meal.adjust.requested",
    "task_id": "",
    "phase": "-",
    "assistant_instance_id": FIXED_INSTANCE_ID,
    "session_id": FIXED_SESSION_ID,
    "event_id": FIXED_EVENT_ID,
    "issued_at": FIXED_ISSUED_AT,
    "nonce": FIXED_NONCE,
    "allowlist_version": ALLOWLIST_VERSION,
    "data": FIXED_DATA,
}

SENSITIVE_PREFIXES = ("fd_ib_", "fd_skill_", "private-")


def _settings() -> Settings:
    """显式构造 settings，避免读开发机 .env 造成结果漂移（jwt_secret >= 32 才能派生 Fernet）。"""
    return Settings(auth={"jwt_secret": "T05-unit-test-jwt-secret-0123456789abcdef"})


def _two_step_sig(env: dict, plaintext: str = PLAINTEXT) -> str:
    """与后端 TokenService.sign 等价的两步 HMAC，用于构造合法/非法验签样本。"""
    signing_key = TokenService.derive_key(plaintext)
    return hmac.new(signing_key, TokenService.canonical(env).encode(), hashlib.sha256).hexdigest()


def _live_env(**over) -> dict:
    """verify 用：issued_at / event_id / nonce 取实时值，才能通过时间窗与防重放。"""
    env = {
        **FIXED_ENVELOPE,
        "issued_at": int(time.time()),
        "event_id": str(uuid4()),
        "nonce": str(uuid4()),
    }
    env.update(over)
    return env


def _model(env: dict, sig: str | None = None, plaintext: str = PLAINTEXT) -> InboundEnvelope:
    return InboundEnvelope(**{**env, "sig": sig or _two_step_sig(env, plaintext)})


@pytest_asyncio.fixture
async def db():
    """aiosqlite 内存库：只建 4 张新表。SQLite 允许外键引用尚不存在的 user 表。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(InboundTokenPair.__table__.create)
        await conn.run_sync(InboundTask.__table__.create)
        await conn.run_sync(InboundAudit.__table__.create)
        await conn.run_sync(InboundBridgeConfig.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_pair(db, svc: TokenService, *, user_id: int = 42, **over) -> InboundTokenPair:
    """手工构造绑定固定 envelope 的 pair，让 verify 能走完整校验链。"""
    now = meal_now()
    values = dict(
        id=FIXED_PAIR_ID,
        user_id=user_id,
        assistant_instance_id=FIXED_INSTANCE_ID,
        session_id=FIXED_SESSION_ID,
        web_token_hash=TokenService._hash(PLAINTEXT),
        assistant_token_hash=TokenService._hash(ASST_PLAINTEXT),
        web_secret_enc=svc.cipher().encrypt(PLAINTEXT.encode()).decode(),
        assistant_secret_enc=svc.cipher().encrypt(ASST_PLAINTEXT.encode()).decode(),
        web_state="active",
        assistant_state="active",
        allowlist_version=ALLOWLIST_VERSION,
        issued_at=now,
        activated_at=now,
        expires_at=now + timedelta(hours=12),
    )
    values.update(over)
    db.add(InboundTokenPair(**values))
    await db.flush()
    return await svc.resolve(FIXED_PAIR_ID)


# ---------------------------------------------------------------- 纯逻辑

def test_canonical_matches_stable_json():
    """canonical 与 stableJSON 一致：中文不转义、键排序、无空白，末行是 sha256。"""
    stable = json.dumps(
        FIXED_DATA, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    assert stable == FIXED_STABLE
    assert "香菜" in stable and "「别太辣」" in stable and "\\u" not in stable
    assert stable.index('"avoid_recent"') < stable.index('"budget"')  # 键排序
    assert stable.index('"context"') < stable.index('"expected_revision"') \
        < stable.index('"instruction"') < stable.index('"request_id"')
    assert ", " not in stable and ": " not in stable and "\n" not in stable  # 无空白

    data_hash = hashlib.sha256(stable.encode()).hexdigest()
    assert data_hash == FIXED_DATA_HASH

    canonical = TokenService.canonical(FIXED_ENVELOPE)
    assert canonical == FIXED_CANONICAL
    lines = canonical.split("\n")
    assert len(lines) == 13
    assert lines[0] == "1" and lines[4] == ""  # v=1 / task_id 空
    assert lines[-1] == FIXED_DATA_HASH

    # 与字段书写顺序无关，且 dict 分支与 InboundEnvelope(getattr 分支) 结果一致
    shuffled = dict(reversed(list(FIXED_ENVELOPE.items())))
    assert TokenService.canonical(shuffled) == canonical
    assert TokenService.canonical(_model(FIXED_ENVELOPE, sig=FIXED_SIG)) == canonical


def test_derive_key_two_step_hmac_and_compare_digest():
    """两步 HMAC、错令牌产生不同 sig、compare_digest 常量时间比较语义。"""
    key = TokenService.derive_key(PLAINTEXT)
    assert isinstance(key, bytes) and len(key) == 32
    assert key.hex() == FIXED_SIGNING_KEY_HEX
    expected = hmac.new(
        PLAINTEXT.encode(), b"fandecide.inbound.sign.v1", hashlib.sha256,
    ).digest()
    assert hmac.compare_digest(key, expected)

    sig = hmac.new(
        key, TokenService.canonical(FIXED_ENVELOPE).encode(), hashlib.sha256,
    ).hexdigest()
    assert sig == FIXED_SIG and len(sig) == 64

    wrong_key = TokenService.derive_key(PLAINTEXT + "x")
    wrong_sig = hmac.new(
        wrong_key, TokenService.canonical(FIXED_ENVELOPE).encode(), hashlib.sha256,
    ).hexdigest()
    assert wrong_sig != FIXED_SIG

    assert hmac.compare_digest(FIXED_SIG, FIXED_SIG)
    assert not hmac.compare_digest(FIXED_SIG, "0" * 64)
    assert not hmac.compare_digest(FIXED_SIG, FIXED_SIG[:-1])


def test_scrub_redacts_three_prefixes():
    """三种敏感前缀全部替换为 [redacted]，非敏感文字保留。"""
    text = "fd_ib_web_A fd_skill_B private-C 正常文本"
    out = scrub(text)
    assert "正常文本" in out
    assert out.count("[redacted]") == 3
    for prefix in SENSITIVE_PREFIXES:
        assert prefix not in out


def test_placeholder_id_is_stable_and_below_2_63():
    """占位主键由 event_id 派生且稳定，落在 BIGINT 正区间（< 2^63）。"""
    first = placeholder_id("t05-event-1")
    assert first == placeholder_id("t05-event-1")
    assert isinstance(first, int) and 0 < first < (1 << 63)
    assert first != placeholder_id("t05-event-2")


def test_outbound_wake_content_scrubs_sensitive_prefixes():
    """出站唤醒内容由服务端固定模板生成，任何敏感前缀都先 scrub 才出站。"""
    content = WakeOrchestrator._content({
        "data": {"instruction": "fd_ib_web_SECRET fd_skill_KEY private-TOKEN"},
    })
    assert "fandecide_inbound_wake" in content
    assert "[redacted]" in content
    for prefix in SENSITIVE_PREFIXES:
        assert prefix not in content


# ---------------------------------------------------------------- 轻量 DB（aiosqlite）

async def test_issue_pair_stores_no_plaintext_and_fernet_rebuilds_key(db):
    """库内无明文、哈希列 == sha256(明文)、Fernet 密文可解密重建签名密钥。"""
    svc = TokenService(db, _settings())
    pair = await svc.issue_pair(42)
    assert pair["web_token"].startswith("fd_ib_web_")
    assert pair["assistant_token"].startswith("fd_ib_asst_")
    assert pair["web_state"] == "active" and pair["assistant_state"] == "active"
    assert pair["allowlist_version"] == ALLOWLIST_VERSION

    row = (await db.execute(select(InboundTokenPair))).scalar_one()
    blob = json.dumps(
        {c.name: str(getattr(row, c.name)) for c in InboundTokenPair.__table__.columns},
        ensure_ascii=False,
    )
    assert "fd_ib_" not in blob  # grep 库内无明文
    assert row.web_token_hash == hashlib.sha256(pair["web_token"].encode()).hexdigest()
    assert row.assistant_token_hash == hashlib.sha256(pair["assistant_token"].encode()).hexdigest()
    assert row.web_token_hash == TokenService._hash(pair["web_token"])

    dec_web = svc.cipher().decrypt(row.web_secret_enc.encode()).decode()
    dec_asst = svc.cipher().decrypt(row.assistant_secret_enc.encode()).decode()
    assert dec_web == pair["web_token"] and dec_asst == pair["assistant_token"]
    assert TokenService.derive_key(dec_web) == TokenService.derive_key(pair["web_token"])


async def test_sign_fixed_vector_via_real_sign_method(db):
    """真实 TokenService.sign 用固定明文签固定 envelope，必须命中跨语言固定 sig。"""
    svc = TokenService(db, _settings())
    pair = await svc.issue_pair(42)
    row = await svc.resolve(pair["pair_id"])
    row.web_secret_enc = svc.cipher().encrypt(PLAINTEXT.encode()).decode()
    row.web_token_hash = TokenService._hash(PLAINTEXT)
    await db.flush()
    assert svc.sign(FIXED_ENVELOPE, "web", row) == FIXED_SIG
    with pytest.raises(BridgeReject) as exc:
        svc.sign(FIXED_ENVELOPE, "not-a-side", row)
    assert exc.value.status == 401 and exc.value.reason_code == "bad_side"


async def test_five_states_single_side_revoke_and_rotate(db):
    """五态迁移与单端撤销/轮换：一端变化不影响另一端，旧令牌哈希立即失效。"""
    svc = TokenService(db, _settings())
    pair = await svc.issue_pair(42)

    row = await svc.resolve(pair["pair_id"])
    assert (row.web_state, row.assistant_state) == ("active", "active")

    # issued -> active（activate 幂等）
    row.web_state = "issued"
    await db.flush()
    await svc.activate(pair["pair_id"], "web")
    assert (await svc.resolve(pair["pair_id"])).web_state == "active"

    # 单端撤销：web=revoked，assistant 仍 active
    await svc.revoke(pair["pair_id"], "web")
    row = await svc.resolve(pair["pair_id"])
    assert row.web_state == "revoked" and row.web_revoked_at is not None
    assert row.assistant_state == "active" and row.assistant_revoked_at is None

    # 单端轮换：只替换 web，assistant 哈希与状态完全不动
    old_web_hash, old_asst_hash = row.web_token_hash, row.assistant_token_hash
    rotated = await svc.rotate(pair["pair_id"], "web")
    row = await svc.resolve(pair["pair_id"])
    assert row.web_token_hash != old_web_hash
    assert row.web_token_hash == TokenService._hash(rotated["token"])
    assert row.web_token_hash != TokenService._hash(pair["web_token"])  # 旧令牌哈希失效
    assert row.assistant_token_hash == old_asst_hash
    assert row.assistant_state == "active"
    assert row.web_state == "active" and row.web_revoked_at is None

    # expired 态
    row.expires_at = meal_now() - timedelta(seconds=1)
    await db.flush()
    assert TokenService.is_expired(row) is True


async def test_consume_event_id_deduplicates(db):
    """防重放：同一 event_id 第一次 True、第二次 False。"""
    svc = TokenService(db, _settings())
    assert await svc.consume_event_id("t05-evt-1") is True
    assert await svc.consume_event_id("t05-evt-1") is False
    assert await svc.consume_event_id("t05-evt-2") is True
    rows = (await db.execute(select(InboundAudit))).scalars().all()
    assert len(rows) == 2


async def test_verify_accepts_valid_envelope(db):
    """先钉住成功路径，后面的拒绝断言才有意义。"""
    svc = TokenService(db, _settings())
    await _seed_pair(db, svc)
    pair = await svc.verify(_model(_live_env()), "web", 42)
    assert pair.id == FIXED_PAIR_ID and pair.user_id == 42


@pytest.mark.parametrize(("over", "reason", "status", "code"), [
    ({"issued_at": 1}, "timestamp_out_of_window", 401, ERR_TOKEN),          # 时间窗过期
    ({"allowlist_version": "ib-0.9"}, "version_mismatch", 403, ERR_ALLOWLIST),  # 版本不匹配
    ({"session_id": "99999999-9999-4999-8999-999999999999"}, "binding_mismatch", 401, ERR_TOKEN),
    ({"assistant_instance_id": "99999999-9999-4999-8999-999999999999"}, "binding_mismatch", 401, ERR_TOKEN),
])
async def test_verify_reject_paths(db, over, reason, status, code):
    """每条都重算合法 sig（否则会先撞在签名校验上），精确断言 status / reason_code / code。"""
    svc = TokenService(db, _settings())
    await _seed_pair(db, svc)
    env = _live_env(**over)
    with pytest.raises(BridgeReject) as exc:
        await svc.verify(_model(env), "web", 42)
    assert exc.value.status == status
    assert exc.value.code == code
    assert exc.value.reason_code == reason


async def test_verify_rejects_cross_user(db):
    """跨用户 expected_user_id -> 404 / 1404 / cross_user。"""
    svc = TokenService(db, _settings())
    await _seed_pair(db, svc, user_id=42)
    with pytest.raises(BridgeReject) as exc:
        await svc.verify(_model(_live_env()), "web", 999)
    assert exc.value.status == 404
    assert exc.value.code == ERR_NOT_FOUND
    assert exc.value.reason_code == "cross_user"


async def test_verify_rejects_bad_signature(db):
    """签名错 -> 401 / bad_signature（compare_digest 语义）。"""
    svc = TokenService(db, _settings())
    await _seed_pair(db, svc)
    with pytest.raises(BridgeReject) as exc:
        await svc.verify(_model(_live_env(), sig="0" * 64), "web", 42)
    assert exc.value.status == 401 and exc.value.reason_code == "bad_signature"


async def test_verify_replay_is_rejected(db):
    """同一 event_id 第二次验签 -> 401 / replay。"""
    svc = TokenService(db, _settings())
    await _seed_pair(db, svc)
    model = _model(_live_env())
    assert (await svc.verify(model, "web", 42)).id == FIXED_PAIR_ID
    with pytest.raises(BridgeReject) as exc:
        await svc.verify(model, "web", 42)
    assert exc.value.status == 401 and exc.value.reason_code == "replay"
