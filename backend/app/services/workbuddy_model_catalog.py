"""Model directory + per-user model selection for the unified direct path.

The directory is read from the SAME artifact dsh-connect-workbuddy writes
(``$DSH_HOME/.workbuddy-catalog.json``): it already carries the upstream credit
multiplier and a free flag per model, so the app never invents a price or a
model the account cannot reach. We READ it; we never write it.

Selection is per-user and deliberately NOT a new table: it is stored as one
``activity_log`` row (``channel='workbuddy'``, ``kind='model_preference'``,
``detail`` = the chosen id, plus the region). That keeps the database schema and
migration state untouched while still being user-scoped and durable.

An empty selection means "auto": prefer a free model, then the plugin's
documented default order. A selection that is no longer in the catalog is kept
in the record but reported as unavailable, so the picker can show the truth
rather than silently switching the user's model.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog

CHANNEL = "workbuddy"
KIND_MODEL = "model_preference"

# Advertised default order used when nothing is configured (matches the plugin's
# own catalog preferences; all of these are free tier on the CN gateway).
_PREFERRED = ("hy4free", "hy3", "step-5-preview", "deepseek-v4.1-flash", "glm-5.3-flash")


def _shape(model: dict) -> dict:
    billing = model.get("billing") if isinstance(model.get("billing"), dict) else {}
    reasoning = model.get("reasoning") if isinstance(model.get("reasoning"), dict) else {}
    credits = billing.get("credits")
    return {
        "id": model.get("id", ""),
        "name": model.get("name", "") or model.get("id", ""),
        "credits": credits if isinstance(credits, str) else "",
        "free": billing.get("free") is True,
        "badges": billing.get("badges") if isinstance(billing.get("badges"), list) else [],
        "context_window": model.get("contextWindow"),
        "max_tokens": model.get("maxTokens"),
        "supports_images": model.get("supportsImages") is True,
        "reasoning": {
            "supported_efforts": reasoning.get("supportedEfforts") or reasoning.get("supported_efforts") or [],
        },
    }


class ModelCatalogService:
    def __init__(self, db: AsyncSession, model_client):
        self.db = db
        self.model_client = model_client

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> list[dict]:
        """Every model the plugin's catalog advertises (both regions merged)."""
        path = self.model_client.catalog_file
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return []
        seen: dict[str, dict] = {}
        for entry in entries.values():
            models = entry.get("models") if isinstance(entry, dict) else None
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                shaped = _shape(model)
                if shaped["id"] and shaped["id"] not in seen:
                    seen[shaped["id"]] = shaped
        return list(seen.values())

    # ------------------------------------------------------------------ selection

    async def selected(self, user_id: int) -> dict:
        """The user's explicit selection, or ``{"model": "", "region": ""}``."""
        row = (await self.db.execute(
            select(ActivityLog).where(
                ActivityLog.user_id == user_id, ActivityLog.kind == KIND_MODEL,
            ).order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc()).limit(1)
        )).scalar_one_or_none()
        if row is None or not (row.detail or "").strip():
            return {"model": "", "region": ""}
        try:
            parsed = json.loads(row.detail)
        except ValueError:
            return {"model": (row.detail or "").strip(), "region": ""}
        if not isinstance(parsed, dict):
            return {"model": "", "region": ""}
        return {
            "model": str(parsed.get("model") or "").strip(),
            "region": str(parsed.get("region") or "").strip(),
        }

    async def choose(self, user_id: int, model_id: str, region: str = "") -> dict:
        """Persist a selection. An empty id means "auto"."""
        catalog = {item["id"] for item in self.catalog()}
        cleaned = (model_id or "").strip()
        if cleaned and catalog and cleaned not in catalog:
            raise ValueError("所选模型不在本机 WorkBuddy 目录里，请刷新后重选")
        selected_region = (region or "").strip()
        if selected_region not in ("", "cn", "global"):
            raise ValueError("区域只能是国内版或国际版")
        self.db.add(ActivityLog(
            user_id=user_id, channel=CHANNEL, kind=KIND_MODEL,
            title="选择模型", detail=json.dumps(
                {"model": cleaned, "region": selected_region}, ensure_ascii=False,
            ),
            status="sent", occurred_at=datetime.now(),
        ))
        await self.db.commit()
        return {"model": cleaned, "region": selected_region}

    def effective_model(self, catalog: list[dict], selection: dict) -> str:
        """Resolve the model actually used: explicit > free > preferred > first."""
        chosen = selection.get("model") or ""
        if chosen:
            return chosen
        free = [item["id"] for item in catalog if item.get("free")]
        for preferred in _PREFERRED:
            if preferred in free:
                return preferred
        if free:
            return free[0]
        for preferred in _PREFERRED:
            if any(item["id"] == preferred for item in catalog):
                return preferred
        return catalog[0]["id"] if catalog else "hy3"

    async def view(self, user_id: int) -> dict:
        catalog = self.catalog()
        selection = await self.selected(user_id)
        effective = self.effective_model(catalog, selection)
        known = {item["id"] for item in catalog}
        return {
            "catalog": catalog,
            "selected": selection.get("model", ""),
            "region": selection.get("region", ""),
            "effective": effective,
            "auto": not selection.get("model"),
            "selection_available": (not selection.get("model")) or (not known) or (
                selection["model"] in known
            ),
        }
