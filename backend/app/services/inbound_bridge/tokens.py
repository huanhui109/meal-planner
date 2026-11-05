"""双向信任中心: 令牌颁发 / 激活 / 轮换 / 撤销 / 签名 / 验签 / 防重放。

两步 HMAC (域分离常量 sign.v1 与 credentials.v1 绝不可互换):
    signing_key = HMAC-SHA256(明文, b"fandecide.inbound.sign.v1").digest()
    sig         = HMAC-SHA256(signing_key, canonical).hexdigest()
Fernet 凭据密钥:
    secret = settings.inbound_bridge.encryption_key or settings.auth.jwt_secret (>=32)
    key    = HMAC-SHA256(secret, b"fandecide.inbound.credentials.v1").digest()

库内只存 sha256(明文) 哈希与 Fernet(明文) 密文, 明文只随 issue_pair / rotate 的返回值
出现一次, 绝不进对话 / 日志 / URL / 命令行参数 / 任务文本 / 出站 content / 错误输出 / 审计表。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.inbound_bridge import InboundAudit, InboundTokenPair
from app.schemas.inbound_bridge import InboundEnvelope
from app.services.meal_service import meal_now

from . import (
    ALLOWLIST_VERSION,
    ERR_ALLOWLIST,
    ERR_DISABLED,
    ERR_NOT_FOUND,
    ERR_SCHEMA,
    ERR_TOKEN,
    SIDE_WEB,
    SIDES,
    BridgeReject,
    placeholder_id,
)

_TOKEN_REJECT = "连接已撤销或过期，请在饭决中重新连接"


def _plain_prefix(side: str) -> str:
    """明文令牌前缀。注意与列名前缀 (web_ / assistant_) 不同, 助手侧是 asst_。"""
    return "fd_ib_web_" if side == SIDE_WEB else "fd_ib_asst_"


class TokenService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    # ---------------------------------------------------------------- 密钥/签名

    def cipher(self) -> Fernet:
        secret = self.settings.inbound_bridge.encryption_key or self.settings.auth.jwt_secret
        if len(secret) < 32:
            raise BridgeReject(503, ERR_DISABLED, "credential_unavailable", "模块尚未就绪，请稍后再试")
        key = hmac.new(secret.encode(), b"fandecide.inbound.credentials.v1", hashlib.sha256).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    @staticmethod
    def derive_key(plaintext: str) -> bytes:
        """第一步 HMAC: 由令牌明文派生 32 字节签名密钥。"""
        return hmac.new(plaintext.encode(), b"fandecide.inbound.sign.v1", hashlib.sha256).digest()

    @staticmethod
    def canonical(envelope) -> str:
        """构造两端逐字一致的签名串。

        envelope 既可以是 InboundEnvelope (入站验签), 也可以是 dict (出站唤醒消息签名)。
        data 字段按排序键序列化后取 sha256, allow_nan=False 会拒绝 NaN/Inf, 与前端 WebCrypto
        实现的等价物一致。
        """
        if isinstance(envelope, dict):
            get = lambda k, d=None: envelope.get(k, d)  # noqa: E731
        else:
            get = lambda k, d=None: getattr(envelope, k, d)  # noqa: E731
        data = get("data", {}) or {}
        data_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest()
        return "\n".join([
            str(get("v")),
            get("pair_id", ""),
            get("direction", ""),
            get("event_type", ""),
            get("task_id", "") or "",
            get("phase", ""),
            get("assistant_instance_id", ""),
            get("session_id", ""),
            get("event_id", ""),
            str(get("issued_at", 0)),
            get("nonce", ""),
            get("allowlist_version", ""),
            data_hash,
        ])

    @staticmethod
    def _hash(plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode()).hexdigest()

    def _plaintext(self, pair: InboundTokenPair, side: str) -> str:
        """解密对应 side 的密文, 取回令牌明文 (仅在内存中使用, 不落日志/响应)。"""
        enc = getattr(pair, f"{side}_secret_enc")
        try:
            plaintext = self.cipher().decrypt(enc.encode()).decode()
        except (InvalidToken, ValueError):
            raise BridgeReject(401, ERR_TOKEN, "credential_error", _TOKEN_REJECT) from None
        if not plaintext.startswith(_plain_prefix(side)) or len(plaintext) > 100:
            raise BridgeReject(401, ERR_TOKEN, "credential_error", _TOKEN_REJECT)
        return plaintext

    def sign(self, envelope, side: str, pair: InboundTokenPair) -> str:
        """第二步 HMAC: 用对应 side 的明文派生密钥对 canonical 签名。

        用于出站唤醒消息 (side="assistant") 与测试中的网页侧签名。返回结果只有 64 位 hex,
        不含任何令牌明文。
        """
        if side not in SIDES:
            raise BridgeReject(401, ERR_TOKEN, "bad_side", _TOKEN_REJECT)
        plaintext = self._plaintext(pair, side)
        try:
            canonical = self.canonical(envelope)
        except Exception:  # noqa: BLE001 - 数据不可序列化 (NaN 等) 一律按签名失败处理
            raise BridgeReject(401, ERR_TOKEN, "bad_signature", _TOKEN_REJECT) from None
        signing_key = self.derive_key(plaintext)
        return hmac.new(signing_key, canonical.encode(), hashlib.sha256).hexdigest()

    # ---------------------------------------------------------------- 验签

    async def verify(self, envelope: InboundEnvelope, side: str, expected_user_id: int | None) -> InboundTokenPair:
        """入站验签。校验顺序严格按契约, 任一失败抛 BridgeReject。

        v -> sig 常量时间 -> 时间窗 -> event_id/nonce 去重 -> pair 存在且对应 side
        active 且未过期 -> allowlist_version 匹配 -> 绑定 user_id / 实例 / 会话一致。
        task_id + phase 绑定留给 ReceiptValidator 做四元匹配。
        """
        if envelope.v != 1:
            raise BridgeReject(401, ERR_TOKEN, "bad_protocol", _TOKEN_REJECT)
        if side not in SIDES:
            raise BridgeReject(401, ERR_TOKEN, "bad_side", _TOKEN_REJECT)

        # 必须先按 pair_id 取到密文, 才能派生密钥验签; 这一步只解析绑定关系, 状态校验后置。
        pair = await self.resolve(envelope.pair_id)
        if pair is None:
            raise BridgeReject(401, ERR_TOKEN, "token_invalid", _TOKEN_REJECT)

        plaintext = self._plaintext(pair, side)
        try:
            canonical = self.canonical(envelope)
        except Exception:  # noqa: BLE001
            raise BridgeReject(401, ERR_TOKEN, "bad_signature", _TOKEN_REJECT) from None
        expected_sig = hmac.new(self.derive_key(plaintext), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, envelope.sig):
            raise BridgeReject(401, ERR_TOKEN, "bad_signature", _TOKEN_REJECT)

        skew = self.settings.inbound_bridge.clock_skew_seconds
        if abs(int(time.time()) - envelope.issued_at) > skew:
            raise BridgeReject(401, ERR_TOKEN, "timestamp_out_of_window", _TOKEN_REJECT)

        if not envelope.nonce:
            raise BridgeReject(401, ERR_TOKEN, "replay", _TOKEN_REJECT)
        if not await self.consume_event_id(envelope.event_id):
            raise BridgeReject(401, ERR_TOKEN, "replay", _TOKEN_REJECT)

        if self.is_expired(pair):
            pair.web_state = "expired"
            pair.assistant_state = "expired"
            await self.db.flush()
            raise BridgeReject(401, ERR_TOKEN, "expired", _TOKEN_REJECT)
        if getattr(pair, f"{side}_state") != "active" or getattr(pair, f"{side}_revoked_at") is not None:
            raise BridgeReject(401, ERR_TOKEN, "token_revoked", _TOKEN_REJECT)

        if envelope.allowlist_version != ALLOWLIST_VERSION:
            raise BridgeReject(403, ERR_ALLOWLIST, "version_mismatch", "本次操作不在允许范围内，已拒绝")

        if expected_user_id is not None and pair.user_id != expected_user_id:
            raise BridgeReject(404, ERR_NOT_FOUND, "cross_user", "找不到这个连接")
        if envelope.assistant_instance_id != pair.assistant_instance_id or envelope.session_id != pair.session_id:
            raise BridgeReject(401, ERR_TOKEN, "binding_mismatch", _TOKEN_REJECT)
        return pair

    # ---------------------------------------------------------------- 防重放

    async def consume_event_id(self, event_id: str) -> bool:
        """用 inbound_audit.event_id UNIQUE 插入占位行实现全局去重。

        成功返回 True (占位行稍后由 AuditService.record 用真实字段覆盖); 重复返回 False。
        用 begin_nested 把唯一键冲突限制在保存点内, 不会冲掉同一事务里的其它写入。
        """
        existing = (await self.db.execute(
            select(InboundAudit.id).where(InboundAudit.event_id == event_id)
        )).first()
        if existing is not None:
            return False
        try:
            async with self.db.begin_nested():
                self.db.add(InboundAudit(
                    id=placeholder_id(event_id),
                    event_id=event_id,
                    user_id=0,
                    direction="",
                    event_type="",
                    outcome="",
                    reason_code="",
                    allowlist_version="",
                ))
                await self.db.flush()
            return True
        except IntegrityError:
            return False

    # ---------------------------------------------------------------- 生命周期

    async def issue_pair(
        self, user_id: int, instance_id: str | None = None, session_id: str | None = None,
    ) -> dict:
        """颁发一对令牌。明文只在返回的 dict 中出现一次, 绝不落库。

        注意: 九个端点里没有单独 /activate, 且颁发动作发生在已登录网页会话中,
        因此两端直接以 active 态出生, 可立即使用; activate() 仍保留用于状态迁移与测试。
        """
        pair_id = str(uuid4())
        instance_id = instance_id or str(uuid4())
        session_id = session_id or str(uuid4())
        web = f"fd_ib_web_{secrets.token_urlsafe(32)}"
        asst = f"fd_ib_asst_{secrets.token_urlsafe(32)}"
        if len(web) > 100 or len(asst) > 100:
            raise BridgeReject(401, ERR_TOKEN, "credential_error", "连接创建失败，请重试")
        cipher = self.cipher()
        now = meal_now()
        ttl = self.settings.inbound_bridge.pair_ttl_seconds
        expires_at = now + timedelta(seconds=ttl)
        pair = InboundTokenPair(
            id=pair_id,
            user_id=user_id,
            assistant_instance_id=instance_id,
            session_id=session_id,
            web_token_hash=self._hash(web),
            assistant_token_hash=self._hash(asst),
            web_secret_enc=cipher.encrypt(web.encode()).decode(),
            assistant_secret_enc=cipher.encrypt(asst.encode()).decode(),
            web_state="active",
            assistant_state="active",
            allowlist_version=ALLOWLIST_VERSION,
            issued_at=now,
            activated_at=now,
            expires_at=expires_at,
        )
        self.db.add(pair)
        await self.db.flush()
        return {
            "pair_id": pair_id,
            "web_token": web,
            "assistant_token": asst,
            "assistant_instance_id": instance_id,
            "session_id": session_id,
            "allowlist_version": ALLOWLIST_VERSION,
            "web_state": "active",
            "assistant_state": "active",
            "expires_at": expires_at.isoformat(),
            "message": "凭据仅显示这一次，请立即保存并关闭窗口；饭决不会再次显示，也不会保存明文。",
        }

    async def activate(self, pair_id: str, side: str) -> None:
        """把某一端从 issued/rotated 迁移到 active (幂等)。"""
        self._check_side(side)
        pair = await self.resolve(pair_id)
        if pair is None:
            raise BridgeReject(404, ERR_NOT_FOUND, "pair_not_found", "找不到这个连接")
        setattr(pair, f"{side}_state", "active")
        if not pair.activated_at:
            pair.activated_at = meal_now()
        await self.db.flush()

    async def rotate(self, pair_id: str, side: str) -> dict:
        """单端轮换: 只替换该 side 的哈希 / 密文 / 状态, 另一端完全不动。

        说明: 迁移 0026 未保留旧密文列, 因此 300s 宽限期无法真正继续接受旧令牌;
        这里如实记录 rotated_at 与宽限值, 旧令牌在哈希替换后立即失效。
        """
        self._check_side(side)
        pair = await self.resolve(pair_id)
        if pair is None:
            raise BridgeReject(404, ERR_NOT_FOUND, "pair_not_found", "找不到这个连接")
        plaintext = f"{_plain_prefix(side)}{secrets.token_urlsafe(32)}"
        if len(plaintext) > 100:
            raise BridgeReject(401, ERR_TOKEN, "credential_error", "轮换失败，请重试")
        cipher = self.cipher()
        setattr(pair, f"{side}_token_hash", self._hash(plaintext))
        setattr(pair, f"{side}_secret_enc", cipher.encrypt(plaintext.encode()).decode())
        setattr(pair, f"{side}_state", "active")
        setattr(pair, f"{side}_revoked_at", None)
        pair.rotated_at = meal_now()
        await self.db.flush()
        return {
            "pair_id": pair.id,
            "side": side,
            "token": plaintext,
            "allowlist_version": pair.allowlist_version,
            "web_state": pair.web_state,
            "assistant_state": pair.assistant_state,
            "grace_seconds": self.settings.inbound_bridge.rotation_grace_seconds,
            "rotated_at": pair.rotated_at.isoformat(),
            "message": "新凭据仅显示这一次；旧凭据已作废（迁移未保留旧密文，宽限期仅作记录）。",
        }

    async def revoke(self, pair_id: str, side: str) -> None:
        """单端撤销: 只置该 side 为 revoked, 不影响另一端在途回执。"""
        self._check_side(side)
        pair = await self.resolve(pair_id)
        if pair is None:
            raise BridgeReject(404, ERR_NOT_FOUND, "pair_not_found", "找不到这个连接")
        setattr(pair, f"{side}_state", "revoked")
        setattr(pair, f"{side}_revoked_at", meal_now())
        await self.db.flush()

    async def resolve(self, pair_id: str) -> InboundTokenPair | None:
        return await self.db.get(InboundTokenPair, pair_id)

    @staticmethod
    def is_expired(pair: InboundTokenPair) -> bool:
        return meal_now() >= pair.expires_at

    @staticmethod
    def _check_side(side: str) -> None:
        if side not in SIDES:
            raise BridgeReject(422, ERR_SCHEMA, "bad_side", "参数 side 必须是 web 或 assistant")
