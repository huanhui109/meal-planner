"""WorkBuddy account sign-in, reusing dsh-connect-workbuddy's verified flow.

The plugin documents the ONE sign-in route it supports for an account that is
not already signed in on the desktop app: a browser/QR OAuth handshake against
the upstream plugin API, not the desktop app's local files. The three steps are
fixed (``src/oauth.ts`` in dsh-connect-workbuddy v5.21.3):

    1. POST {billingBase}/v2/plugin/auth/state?platform=workbuddy
         -> {data:{state, authUrl?}}  ; the user opens authUrl (or /login?state=)
    2. GET  {billingBase}/v2/plugin/auth/token?state=...
         -> {code:0|200, data:{accessToken, refreshToken?, expiresAt|expiresIn,
                                 domain?}}   ; polled until it has a token
    3. GET  {billingBase}/v2/plugin/login/account   (Bearer accessToken)
         -> {data:{uid, nickname?, uin?, enterpriseId?}}

CN is single-homed at ``https://www.codebuddy.cn``; the international product
signs in through ``https://www.workbuddy.ai`` (a token issued at one brand
domain is refused by the other, so the base is chosen BEFORE the state is
issued). The login result is written to the SAME vault the plugin uses, so the
unified chat client discovers it with no extra code path.

Security rules carried over verbatim:
  * The pending session lives in PROCESS MEMORY only; a restart cancels it.
  * The session is bound to ``region`` AND ``base``; a poll naming another
    region never reaches the network.
  * The state is single-use (deleted as soon as a token arrives) and the whole
    session expires after 10 minutes.
  * Tokens never appear in an error message, a log line or a poll response.
  * Nothing is written to the vault that was not obtained from a completed
    handshake; a failed poll writes nothing.

Only httpx + stdlib are used: this is the same protocol the plugin runs, ported
to Python, with no Node/Electron/Cordis dependency.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from app.config import Settings, get_settings
from app.services.workbuddy_model_client import (
    CN_BILLING_BASE,
    GLOBAL_CHAT_BASE,
    scrub,
)

API_PREFIX = "/v2/plugin"
LOGIN_TTL_SECONDS = 600


def billing_base(region: str, explicit: str = "") -> str:
    """The billing base a sign-in for ``region`` starts from."""
    cleaned = (explicit or "").strip().rstrip("/")
    if region == "cn":
        return cleaned or CN_BILLING_BASE
    return cleaned or GLOBAL_CHAT_BASE


@dataclass
class _Session:
    login_id: str
    region: str
    base: str
    state: str
    expires_at: float
    verification_uri: str
    done: bool = False
    error: str = ""
    token: dict = field(default_factory=dict)
    account_id: str = ""
    nickname: str = ""


# Sign-in sessions live for the LIFE OF THE PROCESS, not for one request.
#
# This is module-level on purpose. FastAPI resolves a `Depends` factory once per
# request, so an instance-level map would mean `POST /login` wrote the session
# into instance A while the following `GET /login/{id}` read from a brand-new
# instance B — every poll answered "登录会话不存在". Keeping the map here makes
# the session survive across requests while still dying with the process, which
# is exactly the plugin's stated rule ("a restart cancels").
_SESSIONS: dict[str, _Session] = {}


def _sessions() -> dict[str, _Session]:
    """The process-wide session map (single source for every request)."""
    return _SESSIONS


class WorkBuddyLoginService:
    """In-process, non-persistent sign-in sessions."""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._client = client
        # Shared across every instance: see _SESSIONS above.
        self._sessions = _SESSIONS

    # ------------------------------------------------------------------ helpers

    @property
    def vault_dir(self) -> Path:
        raw = self.settings.workbuddy.vault_dir.strip()
        if raw:
            return Path(raw).expanduser()
        import os

        home = os.getenv("DSH_HOME", "").strip()
        root = Path(home).expanduser() if home else Path.home() / ".dsh"
        return root / "workbuddy-vault"

    async def _request(self, method: str, url: str, **kwargs) -> dict | None:
        timeout = min(30.0, self.settings.workbuddy.model_timeout_seconds)
        try:
            if self._client is not None:
                response = await self._client.request(method, url, timeout=timeout, **kwargs)
            else:
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=False, trust_env=False,
                ) as client:
                    response = await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            return None
        if not 200 <= response.status_code < 300:
            return None
        try:
            document = response.json()
        except ValueError:
            return None
        return document if isinstance(document, dict) else None

    @staticmethod
    def _data(document: dict) -> dict:
        data = document.get("data")
        return data if isinstance(data, dict) else document

    @staticmethod
    def _first(data: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _expiry_ms(data: dict) -> int:
        for key in ("expiresAt", "expires_at"):
            value = data.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value * 1000 if value < 1e11 else value)
        for key in ("expiresIn", "expires_in"):
            value = data.get(key)
            if isinstance(value, (int, float)) and 0 < value < 31_536_000:
                return int((time.time() + float(value)) * 1000)
        return 0

    # ------------------------------------------------------------------ start

    async def start(self, region: str = "cn", base: str = "") -> dict:
        """Ask the upstream for a state; return the URL the user opens."""
        if region not in ("cn", "global"):
            return {"ok": False, "error": "登录区域只能是国内版或国际版"}
        chosen_base = billing_base(region, base)
        document = await self._request(
            "POST",
            f"{chosen_base}{API_PREFIX}/auth/state?platform=workbuddy",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            content=b"{}",
        )
        if document is None:
            return {"ok": False, "error": scrub(f"暂时无法连接 {chosen_base} 发起登录，请稍后重试")}
        data = self._data(document)
        state = self._first(data, ("state", "State"))
        if not state:
            return {"ok": False, "error": "登录服务没有下发 state，请稍后重试"}
        auth_url = self._first(data, ("authUrl", "auth_url", "url", "Url")) or (
            f"{chosen_base}/login?state={state}"
        )
        login_id = f"wbo_{secrets.token_hex(16)}"
        self._sessions[login_id] = _Session(
            login_id=login_id, region=region, base=chosen_base, state=state,
            expires_at=time.time() + LOGIN_TTL_SECONDS, verification_uri=auth_url,
        )
        # Opportunistically drop expired sessions; this map must not grow forever.
        for stale in [k for k, v in self._sessions.items() if v.expires_at < time.time()]:
            self._sessions.pop(stale, None)
        return {
            "ok": True, "login_id": login_id, "region": region,
            "verification_uri": auth_url, "expires_in": LOGIN_TTL_SECONDS,
        }

    # ------------------------------------------------------------------ poll

    async def poll(self, login_id: str, region: str = "") -> dict:
        """Poll once. Terminal on success, refusal, timeout or unknown id.

        A session that ALREADY COMPLETED is answered idempotently for a short
        grace window instead of "not found": the browser may retry the same poll
        (or the client may poll once more before it stops), and a red error
        after a *successful* sign-in would be a lie.
        """
        session = self._sessions.get(login_id)
        if session is None:
            return {"ok": False, "done": True, "error": "登录会话不存在，请重新发起登录"}
        if time.time() > session.expires_at:
            # Report the honest reason BEFORE the sweep drops the row, so an
            # expired sign-in says "timed out" rather than "not found".
            session.done = True
            session.error = "登录超时，请重新发起并完成授权"
            self._sessions.pop(login_id, None)
            return {"ok": False, "done": True, "error": session.error}
        # Trim OTHER expired sessions; this map must not grow forever.
        for stale in [k for k, v in self._sessions.items() if v.expires_at < time.time()]:
            self._sessions.pop(stale, None)
        if region and region != session.region:
            return {"ok": False, "done": True, "error": "登录会话属于另一个版本，请重新发起"}
        if session.done:
            if session.error:
                return self._terminal(session)
            # Idempotent success replay for a bounded window.
            return {
                "ok": True, "done": True, "region": session.region,
                "account_id": session.account_id, "nickname": session.nickname,
                "message": "登录已完成",
            }

        document = await self._request(
            "GET",
            f"{session.base}{API_PREFIX}/auth/token?state={session.state}",
            headers={"Accept": "application/json"},
        )
        if document is None:
            return {"ok": True, "done": False, "message": "等待你在浏览器完成授权"}
        code = document.get("code")
        if isinstance(code, int) and code not in (0, 200):
            return {"ok": True, "done": False, "message": "等待你在浏览器完成授权"}
        data = self._data(document)
        access_token = self._first(data, ("accessToken", "access_token", "AccessToken"))
        if not access_token:
            return {"ok": True, "done": False, "message": "等待你在浏览器完成授权"}

        session.done = True
        session.token = data
        profile = await self._profile(session, access_token, data)
        account_id = self._write_vault(session, access_token, data, profile)
        # Keep a short-lived completed marker so a duplicate poll answers the
        # TRUTH ("already done") instead of "session not found". It is dropped by
        # the same expiry sweep that trims abandoned sessions.
        session.account_id = account_id
        session.nickname = profile.get("nickname", "")
        session.expires_at = min(session.expires_at, time.time() + 60)
        return {
            "ok": True, "done": True, "region": session.region,
            "account_id": account_id,
            "nickname": profile.get("nickname", ""),
            "message": "登录完成，已写入本机连接",
        }

    async def _profile(self, session: _Session, access_token: str, token_data: dict) -> dict:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        domain = self._first(token_data, ("domain", "Domain"))
        if domain:
            headers["X-Domain"] = domain
        document = await self._request(
            "GET", f"{session.base}{API_PREFIX}/login/account", headers=headers,
        )
        if document is None:
            return {}
        data = self._data(document)
        return {
            "uid": self._first(data, ("uid", "Uid", "userId", "UserID")),
            "nickname": self._first(data, ("nickname", "NickName", "ScreenName")),
            "uin": self._first(data, ("uin", "Uin")),
            "domain": self._first(data, ("domain", "Domain")),
        }

    # ------------------------------------------------------------------ vault

    def _write_vault(self, session: _Session, access_token: str, token_data: dict, profile: dict) -> str:
        """Write the plugin's own vault document shape, 0600, atomically.

        This is the ONE place the app writes a credential, and only from a
        completed handshake. The desktop app's own auth files are never touched.
        """
        account_id = (
            profile.get("uid") or profile.get("uin")
            or self._first(token_data, ("accountId", "account_id"))
            or secrets.token_hex(12)
        )
        # The plugin derives the file id as sha256(identity)[:24]; keep the same
        # shape so the two tools agree, but tolerate any stable id.
        import hashlib

        digest = hashlib.sha256(str(account_id).encode()).hexdigest()[:24]
        expires_at = self._expiry_ms(token_data)
        domain = (
            self._first(token_data, ("domain", "Domain"))
            or profile.get("domain", "")
            or ("www.workbuddy.ai" if session.region == "global" else "www.workbuddy.cn")
        )
        document = {
            "version": 2,
            "accountId": digest,
            "refreshedAtMs": int(time.time() * 1000),
            "auth": {
                "accessToken": access_token,
                "refreshToken": self._first(token_data, ("refreshToken", "refresh_token", "RefreshToken")),
                "expiresAt": int(expires_at / 1000) if expires_at else int(time.time()) + 3600,
                "domain": domain,
            },
            "account": {
                "uid": profile.get("uid", ""),
                "nickname": profile.get("nickname", ""),
                "uin": profile.get("uin", ""),
            },
        }
        target_dir = self.vault_dir / session.region
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{digest}.json"
        tmp = target.with_suffix(".json.tmp")
        import json
        import os

        payload = json.dumps(document, ensure_ascii=False)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return digest

    # ------------------------------------------------------------------ misc

    def _terminal(self, session: _Session) -> dict:
        if session.error:
            return {"ok": False, "done": True, "error": session.error}
        return {"ok": True, "done": True, "region": session.region, "message": "登录已完成"}

    async def logout(self, region: str = "") -> dict:
        """Remove plugin-owned vault copies (the desktop app keeps its sign-in).

        Pending (not-yet-completed) sessions for that region are dropped too: a
        poll that arrives after "退出登录" must not resurrect a credential the
        user just removed. Completed markers are also cleared for the region.
        """
        removed = 0
        for path in sorted(self.vault_dir.glob("*/*.json")):
            if region and path.parent.name != region:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        for login_id in [
            k for k, v in self._sessions.items() if not region or v.region == region
        ]:
            self._sessions.pop(login_id, None)
        return {"ok": True, "removed": removed}


def get_workbuddy_login_service() -> WorkBuddyLoginService:
    """FastAPI dependency.

    Returns a NEW service object each request (cheap: it only holds settings and
    an optional transport), but the SESSION MAP is process-wide, so a login
    started by one request is pollable by the next. Do not give this service
    request-scoped state.
    """
    return WorkBuddyLoginService()
