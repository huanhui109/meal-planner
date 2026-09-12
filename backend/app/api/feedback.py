"""F8 反馈 API

设计要点:
- 匿名可提交 (user_id 可空): 用户首次启动就能反馈, 无需登录
- 不做实时通知, 后台通过 /api/admin/feedback 拉取 (V2.6 落地)
- 节流: 同一用户/同一 device 24h 内最多 5 条
"""
from __future__ import annotations

from datetime import datetime, timedelta
from json import dumps, loads
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user_optional, get_db
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.feedback import FeedbackCreate

router = APIRouter(prefix="/feedback", tags=["反馈"])

DAILY_LIMIT = 5


def _escape_like(value: str) -> str:
    """like 通配符转义, 避免 % / _ 被当成模式字符"""
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def _check_rate_limit(db: AsyncSession, user_id: Optional[int], ip: str) -> None:
    """24h 内同一 user_id 或 ip 提交条数不超过 DAILY_LIMIT"""
    since = datetime.utcnow() - timedelta(hours=24)

    conditions = []
    if user_id is not None:
        conditions.append(Feedback.user_id == user_id)
    conditions.append(Feedback.device_info.like(f'%"ip":"{_escape_like(ip)}"%', escape="\\"))

    query = select(func.count(Feedback.id)).where(Feedback.created_at >= since)
    query = query.where(or_(*conditions))

    result = await db.execute(query)
    count = result.scalar_one() or 0
    if count >= DAILY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"24 小时内已提交 {count} 条反馈, 稍后再来吧 (上限 {DAILY_LIMIT} 条)",
        )


@router.post("", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    data: FeedbackCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """提交反馈

    - 已登录: user_id 自动绑定
    - 未登录 (匿名): user_id 留空, 但仍受 IP 限流约束
    """
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(db, user.id if user else None, client_ip)

    device_payload = data.device_info or ""
    if device_payload:
        try:
            parsed = loads(device_payload)
            if isinstance(parsed, dict):
                parsed["ip"] = client_ip
                device_payload = dumps(parsed, ensure_ascii=False)
        except (ValueError, TypeError):
            # device_info 不是合法 JSON, 仍记录但不附加 ip
            pass

    item = Feedback(
        user_id=user.id if user else None,
        category=data.category,
        content=data.content.strip(),
        contact=data.contact.strip() if data.contact else None,
        device_info=device_payload or None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return SuccessResponse(
        code=0,
        message="已收到, 谢谢反馈",
        data={
            "id": item.id,
            "category": item.category,
            "status": item.status,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        },
    )


@router.get("/mine", response_model=SuccessResponse)
async def list_my_feedback(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    """我提交的反馈 (最近 20 条)

    匿名反馈因为无法关联 user 全部返回空列表
    """
    if user is None:
        return SuccessResponse(code=0, message="success", data={"total": 0, "items": []})

    result = await db.execute(
        select(Feedback)
        .where(Feedback.user_id == user.id)
        .order_by(Feedback.created_at.desc())
        .limit(20)
    )
    items = result.scalars().all()
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "total": len(items),
            "items": [
                {
                    "id": item.id,
                    "category": item.category,
                    "content": item.content,
                    "status": item.status,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in items
            ],
        },
    )
