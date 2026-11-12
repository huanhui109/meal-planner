"""Unified in-app direct model request, aligned with dsh-connect-workbuddy.

The upstream ``dsh-connect-workbuddy`` plugin (v5.21.3) reuses the *locally
signed-in* WorkBuddy desktop account. It does not run an official OAuth flow;
instead it decrypts/refreshes the desktop auth document and keeps a plaintext
copy in ``$DSH_HOME/workbuddy-vault/<region>/<accountId>.json``, and it writes the
model catalog to ``$DSH_HOME/.workbuddy-catalog.json``. Its OpenAI-compatible
loopback shim uses a random port and an in-process secret (both non-persistent),
so a separate process cannot call the shim itself. What IS reusable is the
stable on-disk connection artifacts plus the upstream wire protocol.

This module therefore:
  * READS (never writes) those artifacts, choosing a region by ``auth.domain``;
  * refreshes an expiring token the same way the plugin does
    (``POST /v2/plugin/auth/token/refresh`` with ``X-Refresh-Token``, 5-minute
    margin, single-flight, keep the old token when refresh fails but is valid);
  * calls ``POST {chatBase}/v2/chat/completions`` with CLI-shaped headers, a
    leading ``system`` message and forced ``stream:true``, then consumes the SSE
    stream to a terminal ``data: [DONE]``;
  * returns a *checked envelope* (``ok`` first, then content), exactly the rule
    the plugin documents for ``chatStream()`` — consuming the body without
    checking ``ok`` is how failures get reported as successes.

No Node, Cordis, pi-ai, Electron or new dependency is used: only httpx + stdlib.
The desktop app 5.6+ encrypts auth fields with a build-time key that only the
installed Electron binary can expose; a Python backend cannot bootstrap from
that. On such machines ``available`` is false and the app degrades gracefully.
Tokens and refresh tokens MUST NOT appear in any returned message, log line or
exception. ``refresh`` tokens are NEVER sent on a chat request.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import Settings, get_settings

# Gateways measured by dsh-connect-workbuddy (upstream.ts / cn-gateway.ts).
CN_CHAT_BASE = "https://copilot.tencent.com"
GLOBAL_CHAT_BASE = "https://www.workbuddy.ai"
CN_BILLING_BASE = "https://www.codebuddy.cn"

# The plugin's chat channel is ALWAYS the CLI channel; the catalog read uses the
# App channel User-Agent. Keep the two distinct (the plugin documents why).
CLIENT_UA = "CLI/2.63.2 CodeBuddy/2.63.2"
PRODUCT_UA = "WorkBuddy/5.8.3 WorkBuddy/5.8.3 CLI/2.161.0"

CHAT_PATH = "/v2/chat/completions"
REFRESH_PATH = "/v2/plugin/auth/token/refresh"

# Business codes the plugin classifies. We only map them to honest Chinese text;
# no retry / failover / fingerprint-perturbation arms race is ported.
_KIND_MESSAGES = {
    "hard_credit": "WorkBuddy 积分不足，请更换账号或稍后再试",
    "soft_rate": "WorkBuddy 请求较多，已被限流，请稍后再试",
    "model_busy": "这个模型此刻较忙，请换一个模型或稍后再试（与账号积分无关）",
    "model_queue": "模型排队中，请稍后重新发送或换一个模型",
    "session_dead": "WorkBuddy 登录态已失效，请在桌面端重新登录",
    "policy_reject": "请求被 WorkBuddy 按内容策略拒绝，请调整要求后重试",
    "account_restricted": "该账号被上游限制，请改用官方 WorkBuddy 客户端",
    "channel_reject": "WorkBuddy 网关拒绝了本次第三方渠道请求（上游策略）",
    "context_too_long": "这一餐的上下文过长，请新开一轮或缩短要求",
    "not_found": "所选模型不可用，请改选模型",
    "server": "WorkBuddy 上游暂时不可用，请稍后再试",
    "client": "WorkBuddy 未接受本次请求，请检查要求后重试",
}
_CODE_KIND = {
    6004: "soft_rate",
    14003: "model_busy",
    11128: "channel_reject",
    11140: "policy_reject",
    11115: "context_too_long",
    14018: "hard_credit",
    6020: "model_queue",
    6021: "model_queue",
    6022: "model_queue",
    11133: "client",
}

_SENSITIVE_PREFIXES = ("fd_ib_", "fd_skill_", "private-")


def scrub(text: str) -> str:
    """Drop known sensitive token prefixes from anything that can leave the process."""
    for prefix in _SENSITIVE_PREFIXES:
        text = text.replace(prefix, "[redacted]")
    return text


@dataclass
class ChatEnvelope:
    """Checked result of one upstream chat call.

    Mirrors ``WorkBuddyChatResult`` in dsh-connect-workbuddy: ALWAYS inspect
    ``ok`` before reading ``text``. ``text`` is ``None`` on failure.
    """

    ok: bool
    text: Optional[str] = None
    model: str = ""
    region: str = ""
    status: int = 0
    kind: str = ""
    message: str = ""

    @classmethod
    def success(cls, text: str, *, model: str, region: str) -> ChatEnvelope:
        return cls(ok=True, text=text, model=model, region=region)

    @classmethod
    def failure(cls, status: int, kind: str, message: str) -> ChatEnvelope:
        return cls(ok=False, status=status, kind=kind, message=scrub(message))


class WorkBuddyModelError(Exception):
    """A problem with the local connection artifacts (kept token-free)."""


class WorkBuddyModelClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_settings()
        self._client = client
        # In-process only: refreshed tokens MUST NOT be written back to the vault.
        self._refreshed: dict[str, dict] = {}
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------ paths

    @property
    def _dsh_home(self) -> Path:
        raw = os.getenv("DSH_HOME", "").strip()
        return Path(raw).expanduser() if raw else Path.home() / ".dsh"

    @property
    def vault_dir(self) -> Path:
        raw = self.settings.workbuddy.vault_dir.strip()
        return Path(raw).expanduser() if raw else self._dsh_home / "workbuddy-vault"

    @property
    def catalog_file(self) -> Path:
        raw = self.settings.workbuddy.catalog_file.strip()
        return Path(raw).expanduser() if raw else self._dsh_home / ".workbuddy-catalog.json"

    def chat_base(self, region: str) -> str:
        cfg = self.settings.workbuddy
        override = cfg.chat_base_global if region == "global" else cfg.chat_base_cn
        return (override.strip() or (GLOBAL_CHAT_BASE if region == "global" else CN_CHAT_BASE)).rstrip("/")

    # ------------------------------------------------------------------ vault

    @staticmethod
    def _region_of(domain: str) -> str:
        lowered = (domain or "").lower()
        if "workbuddy.ai" in lowered or "codebuddy.ai" in lowered:
            return "global"
        return "cn"

    def _vault_files(self) -> list[Path]:
        root = self.vault_dir
        if not root.is_dir():
            return []
        files = sorted(p for p in root.glob("*/*.json") if p.is_file())
        return files

    @staticmethod
    def _parse_credential(path: Path) -> dict | None:
        """Return a normalized credential dict, or None when unusable.

        The vault document is the plugin's own shape (verified against the
        installed copy)::

            {"version":2,"accountId":"...","auth":{"accessToken":...,
             "refreshToken":...,"expiresAt":<epoch seconds>,"domain":...},
             "account":{"uid":...,"nickname":...}}
        """
        try:
            stat = path.stat()
            if hasattr(os, "getuid") and stat.st_uid != os.getuid():
                return None  # never read somebody else's token file
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        auth = data.get("auth")
        if not isinstance(auth, dict):
            return None
        token = auth.get("accessToken")
        if not isinstance(token, str) or not 10 <= len(token) <= 8192:
            return None
        expires_at = auth.get("expiresAt")
        if not isinstance(expires_at, (int, float)) or expires_at <= 0:
            return None
        # Vault uses epoch SECONDS (verified: 1796959366 -> 2026-12-11).
        if expires_at > 1e11:  # tolerate a milliseconds build
            expires_at = expires_at / 1000
        return {
            "account_id": str(data.get("accountId") or path.stem),
            "access_token": token,
            "refresh_token": auth.get("refreshToken") if isinstance(auth.get("refreshToken"), str) else "",
            "expires_at": float(expires_at),
            "refresh_expires_at": auth.get("refreshExpiresAt"),
            "domain": str(auth.get("domain") or ""),
            "region": WorkBuddyModelClient._region_of(str(auth.get("domain") or "")),
        }

    def _candidates(self) -> list[dict]:
        out: list[dict] = []
        for path in self._vault_files():
            cred = self._parse_credential(path)
            if cred is not None:
                out.append(cred)
        # Domestic first (matches the plugin's regionOrder=cn,global default),
        # then the token that expires latest. Deterministic, no random spend.
        out.sort(key=lambda c: (0 if c["region"] == "cn" else 1, -c["expires_at"]))
        return out

    def _apply_refresh(self, cred: dict, refreshed: dict) -> None:
        """Fold a refresh response into an in-memory credential copy."""
        token_field = refreshed.get("accessToken") or refreshed.get("access_token")
        if isinstance(token_field, str) and token_field:
            cred["access_token"] = token_field
        refresh_field = refreshed.get("refreshToken") or refreshed.get("refresh_token")
        if isinstance(refresh_field, str) and refresh_field:
            cred["refresh_token"] = refresh_field
        expires_in = refreshed.get("expiresIn") or refreshed.get("expires_in")
        if isinstance(expires_in, (int, float)) and 0 < expires_in < 31_536_000:
            cred["expires_at"] = time.time() + float(expires_in)
        else:
            expires_at = refreshed.get("expiresAt") or refreshed.get("expires_at")
            if isinstance(expires_at, (int, float)) and expires_at > 0:
                cred["expires_at"] = float(expires_at / 1000 if expires_at > 1e11 else expires_at)
        domain = refreshed.get("domain")
        if isinstance(domain, str) and domain:
            cred["domain"] = domain
            cred["region"] = self._region_of(domain)

    async def _refresh(self, cred: dict) -> bool:
        """Refresh with the plugin's endpoint. Returns True when usable.

        Single-flight per account; a failed refresh is NOT fatal while the old
        token is still within its validity window (plugin's own rule).
        """
        if not cred.get("refresh_token"):
            return False
        async with self._refresh_lock:
            cached = self._refreshed.get(cred["account_id"])
            if cached and cached["expires_at"] > time.time() + 300:
                self._apply_refresh(cred, cached["refreshed"])
                return True
            body = json.dumps({}).encode()
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": CLIENT_UA,
                "X-Requested-With": "XMLHttpRequest",
                "X-Refresh-Token": cred["refresh_token"],
                "X-Auth-Refresh-Source": "workbuddy",
                "X-CodeBuddy-Request": "1",
                "X-IDE-Name": "WorkBuddy",
                "X-IDE-Type": "CLI",
                "X-Product": "WorkBuddy",
                "X-Domain": cred["domain"] or "www.workbuddy.cn",
            }
            url = f"{self.chat_base(cred['region'])}{REFRESH_PATH}"
            try:
                if self._client is not None:
                    response = await self._client.post(url, content=body, headers=headers)
                else:
                    async with httpx.AsyncClient(
                        timeout=min(20.0, self.settings.workbuddy.model_timeout_seconds),
                        follow_redirects=False, trust_env=False,
                    ) as client:
                        response = await client.post(url, content=body, headers=headers)
            except httpx.HTTPError:
                return False
            if not 200 <= response.status_code < 300:
                return False
            try:
                payload = response.json()
            except ValueError:
                return False
            # Envelope {code, msg, data}; clean = code 0.
            if not isinstance(payload, dict) or payload.get("code") not in (None, 0):
                return False
            data = payload.get("data", payload)
            if not isinstance(data, dict):
                return False
            self._refreshed[cred["account_id"]] = {
                "expires_at": time.time() + 300,
                "refreshed": data,
            }
            self._apply_refresh(cred, data)
            return True

    async def resolve(self) -> dict | None:
        """Pick a usable credential (read-only vault + in-memory refresh)."""
        for cred in self._candidates():
            if cred["expires_at"] > time.time() + 300:
                return cred
            if await self._refresh(cred) and cred["expires_at"] > time.time():
                return cred
            # Old token still valid (just inside the 5-minute margin): use it.
            if cred["expires_at"] > time.time() + 30:
                return cred
        return None

    # ------------------------------------------------------------------ catalog

    def choose_model(self) -> str:
        """Pick a model id: explicit config > catalog free tier > safe default.

        Reads the plugin's own catalog file; never guesses a model the account
        cannot reach and never writes the catalog.
        """
        configured = self.settings.workbuddy.model.strip()
        if configured:
            return configured
        try:
            data = json.loads(self.catalog_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "hy3"
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return "hy3"
        ids: list[str] = []
        free: list[str] = []
        for entry in entries.values():
            models = entry.get("models") if isinstance(entry, dict) else None
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                mid = model.get("id")
                if not isinstance(mid, str) or not mid:
                    continue
                ids.append(mid)
                billing = model.get("billing")
                if isinstance(billing, dict) and billing.get("free") is True:
                    free.append(mid)
        # Prefer a free model, favoring the plugin's advertised default order.
        for preferred in ("hy4free", "hy3", "step-5-preview", "deepseek-v4.1-flash"):
            if preferred in free:
                return preferred
        if free:
            return free[0]
        return ids[0] if ids else "hy3"

    # ------------------------------------------------------------------ status

    async def status(self) -> dict:
        """Read-only, no chat request. Reports the truthful connection state."""
        cred = await self.resolve()
        if cred is None:
            return {
                "available": False, "region": "", "model": "",
                "message": "本机 WorkBuddy 登录态不可用：请确认 dsh-connect-workbuddy 已登录且凭据库可读，"
                           "或改用「复制任务到助手」/ Skill 连接",
            }
        model = self.choose_model()
        return {
            "available": True,
            "region": cred["region"],
            "model": model,
            "message": f"本机 WorkBuddy 已登录（{cred['region']}），应用内可直接向 {model} 发起模型请求",
        }

    # ------------------------------------------------------------------ headers

    @staticmethod
    def _headers(cred: dict) -> dict[str, str]:
        """CLI-shaped headers measured by dsh-connect-workbuddy.

        Crucially: NO ``X-Refresh-Token`` on a chat request. The conversation
        identity triple is freshly generated per request (the international
        gateway rejects requests without it).
        """
        conversation = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        message_id = uuid.uuid4().hex
        global_region = cred["region"] == "global"
        origin = GLOBAL_CHAT_BASE if global_region else CN_BILLING_BASE
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": CLIENT_UA,
            "Authorization": f"Bearer {cred['access_token']}",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": origin,
            "Referer": f"{origin}/",
            "Accept-Language": "zh-CN",
            "X-Domain": cred["domain"] or ("www.workbuddy.ai" if global_region else "www.workbuddy.cn"),
            "X-No-User-Id": "1",
            "X-No-Enterprise-Id": "1",
            "X-No-Department-Info": "1",
            "X-Agent-Purpose": "conversation",
            "X-IDE-Name": "WorkBuddy",
            "X-IDE-Type": "CLI",
            "X-Product": "WorkBuddy",
            "X-CodeBuddy-Request": "1",
            "X-Conversation-ID": conversation,
            "X-Conversation-Request-ID": request_id,
            "X-Conversation-Message-ID": message_id,
            "X-Root-Request-ID": request_id,
            "X-Request-ID": request_id,
        }

    # ------------------------------------------------------------------ chat

    @staticmethod
    def _parse_sse_line(line: str, pieces: list[str]) -> tuple[bool, Optional[dict]]:
        """Feed one SSE line; return (done, error_envelope)."""
        if not line:
            return False, None
        stripped = line.strip()
        if not stripped.startswith("data:"):
            return False, None
        payload = stripped[5:].strip()
        if payload == "[DONE]":
            return True, None
        try:
            frame = json.loads(payload)
        except ValueError:
            return False, None
        if not isinstance(frame, dict):
            return False, None
        # Upstream business errors arrive either as an SSE frame or as a plain
        # JSON envelope. Either way surface it as an error, never as content.
        if frame.get("code") not in (None, 0):
            return False, frame
        choices = frame.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            if isinstance(delta, dict):
                content = delta.get("content")
                # Deliberately ignore `reasoning_content` (thinking): it is not
                # the answer channel and must not be parsed as a JSON receipt.
                if isinstance(content, str) and content:
                    pieces.append(content)
        return False, None

    @staticmethod
    def _classify_status(status: int) -> tuple[str, str]:
        if status in (401, 403):
            return "session_dead", _KIND_MESSAGES["session_dead"]
        if status == 429:
            return "soft_rate", _KIND_MESSAGES["soft_rate"]
        if status == 402:
            return "hard_credit", _KIND_MESSAGES["hard_credit"]
        if status >= 500:
            return "server", _KIND_MESSAGES["server"]
        return "client", _KIND_MESSAGES["client"]

    @classmethod
    def _classify_envelope(cls, payload: dict, status: int) -> tuple[str, str]:
        code = payload.get("code")
        if isinstance(code, int) and code in _CODE_KIND:
            kind = _CODE_KIND[code]
            return kind, _KIND_MESSAGES.get(kind, _KIND_MESSAGES["client"])
        return cls._classify_status(status)

    async def chat(self, prompt: str, *, model: str = "", system: str = "") -> ChatEnvelope:
        """Call the signed-in WorkBuddy model once. Check ``ok`` before ``text``.

        ``prompt`` is the full instruction/data block built by the orchestrator.
        A leading ``system`` message and ``stream:true`` are enforced here, as the
        upstream gateway rejects bodies without them. ``system`` defaults to the
        饭决 skill contract so EVERY call is confined to meal-planner output.
        """
        cred = await self.resolve()
        if cred is None:
            return ChatEnvelope.failure(
                503, "session_dead",
                "本机 WorkBuddy 登录态不可用：请确认已登录，或复制任务到助手处理；原方案未改变",
            )
        chosen = (model or self.choose_model()).strip() or "hy3"
        from app.services import dish_candidate_skill as candidate_skill
        from app.services.fandecide_skill_contract import SYSTEM_CONTRACT

        # EVERY call is confined to a skill contract. Which one is decided by the
        # fixed first line of the generated prompt (never by user-controlled text):
        # the candidate skill may nominate new dishes, the selection skill may not.
        # Sending the selection contract to a generation task used to contradict
        # its own instruction ("不得新增候选") and produced empty replies.
        default_system = (
            candidate_skill.SYSTEM_CONTRACT
            if prompt.startswith(candidate_skill.PROMPT_LEAD)
            else SYSTEM_CONTRACT
        )
        body = {
            "model": chosen,
            "stream": True,
            "messages": [
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt},
            ],
        }
        # Low latency is a product requirement, not a tuning afterthought: cap the
        # reply length and keep sampling deterministic. 0 / None disables a field
        # for upstreams that reject it. Both are per-instance settings, so chat()'s
        # signature stays untouched and every injected test double keeps working.
        max_tokens = self.settings.workbuddy.chat_max_tokens
        if max_tokens > 0:
            body["max_tokens"] = max_tokens
        temperature = self.settings.workbuddy.chat_temperature
        if temperature is not None:
            body["temperature"] = temperature
        body_bytes = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        url = f"{self.chat_base(cred['region'])}{CHAT_PATH}"
        timeout = self.settings.workbuddy.model_timeout_seconds
        pieces: list[str] = []
        try:
            if self._client is not None:
                # Injected client (tests / shared transport). Use stream() when
                # available, otherwise fall back to a plain request.
                if hasattr(self._client, "stream"):
                    async with self._client.stream(
                        "POST", url, content=body_bytes, headers=self._headers(cred), timeout=timeout,
                    ) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            return await self._http_failure(response, status)
                        async for line in response.aiter_lines():
                            done, error = self._parse_sse_line(line, pieces)
                            if error is not None:
                                kind, message = self._classify_envelope(error, status)
                                return ChatEnvelope.failure(status, kind, message)
                            if done:
                                break
                else:
                    response = await self._client.post(
                        url, content=body_bytes, headers=self._headers(cred), timeout=timeout,
                    )
                    status = response.status_code
                    if not 200 <= status < 300:
                        return await self._http_failure(response, status)
                    async for line in response.aiter_lines():
                        done, error = self._parse_sse_line(line, pieces)
                        if error is not None:
                            kind, message = self._classify_envelope(error, status)
                            return ChatEnvelope.failure(status, kind, message)
                        if done:
                            break
            else:
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=False, trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST", url, content=body_bytes, headers=self._headers(cred),
                    ) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            return await self._http_failure(response, status)
                        async for line in response.aiter_lines():
                            done, error = self._parse_sse_line(line, pieces)
                            if error is not None:
                                kind, message = self._classify_envelope(error, status)
                                return ChatEnvelope.failure(status, kind, message)
                            if done:
                                break
        except httpx.TimeoutException:
            return ChatEnvelope.failure(
                504, "server", "WorkBuddy 模型请求超时；本次不会自动重发，原方案未改变",
            )
        except httpx.HTTPError:
            return ChatEnvelope.failure(
                502, "server", "暂时无法连接 WorkBuddy 上游；本次不会自动重发，原方案未改变",
            )
        text = "".join(pieces).strip()
        if not text:
            return ChatEnvelope.failure(
                502, "server", "WorkBuddy 未返回可用的模型回复；本次不会自动重发，原方案未改变",
            )
        return ChatEnvelope.success(text, model=chosen, region=cred["region"])

    async def _http_failure(self, response: Any, status: int) -> ChatEnvelope:
        """Classify a non-2xx response without ever echoing its body verbatim.

        A response opened with ``client.stream()`` has NOT read its body yet, so
        ``response.json()`` raises ``ResponseNotRead``. Read it explicitly first,
        and treat a body we still cannot parse as an opaque failure — never let a
        diagnostic step turn a clean 4xx into an unexpected exception.
        """
        payload = None
        try:
            if hasattr(response, "aread"):
                await response.aread()
            payload = response.json()
        except Exception:  # noqa: BLE001 - any parse issue must not escape
            payload = None
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            kind, message = self._classify_envelope(payload, status)
        else:
            kind, message = self._classify_status(status)
        return ChatEnvelope.failure(status, kind, message)


def get_workbuddy_model_client() -> WorkBuddyModelClient:
    """FastAPI dependency factory (overridable in tests, like get_workbuddy_client)."""
    return WorkBuddyModelClient()
