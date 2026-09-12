"""T2.6 事件上报 API - 小程序/H5 客户端把行为日志打到这里

不鉴权 (匿名事件也能上报), 失败不抛 4xx (即便事件语法不对也静默接受) —
埋点跟业务不一样, 客户端永远要能 fire-and-forget, 出问题不影响主流程
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user_optional, get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.events import EventBatchAck, EventBatchIn

router = APIRouter(prefix="/events", tags=["埋点"])

ALLOWED_PLATFORM = {"weapp", "h5", "mini-app", "unknown"}


def _normalize_platform(value: str | None) -> str:
    if not value:
        return "unknown"
    if value in ALLOWED_PLATFORM:
        return value
    # 截断到 40 字符并替换不可见字符
    cleaned = "".join(c for c in value if c.isprintable())[:40]
    return cleaned or "unknown"


@router.post("", response_model=SuccessResponse)
async def report_events(
    payload: EventBatchIn,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """批量上报: 单批 1-50 条, 最多 5KB/条

    user_id 自动绑定 (登录用户); 失败原因只在控制台打印
    """
    accepted = 0
    skipped = 0
    user_id = user.id if user else None
    for raw in payload.events:
        try:
            properties_json = (
                json.dumps(raw.properties, ensure_ascii=False) if raw.properties else None
            )
            # 拦截过大单条 (5KB 阈值)
            if properties_json and len(properties_json.encode("utf-8")) > 5 * 1024:
                skipped += 1
                continue
            row = Event(
                user_id=user_id,
                event_name=raw.event_name,
                ts=raw.ts,
                properties=properties_json,
                app_version=raw.app_version,
                platform=_normalize_platform(raw.platform),
            )
            db.add(row)
            accepted += 1
        except Exception:  # noqa: BLE001 - 埋点失败不影响业务
            skipped += 1
            continue
    await db.commit()
    return SuccessResponse(
        code=0,
        message="success",
        data=EventBatchAck(accepted=accepted, skipped=skipped).model_dump(),
    )
