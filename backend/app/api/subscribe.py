"""T2.2 订阅消息 API

GET  /api/subscribe/templates        — 列出可订阅的模板
POST /api/subscribe/grant            — 用户授权/拒绝记录
GET  /api/subscribe/status/{tid}     — 查询某模板授权状态

模板内容是写死的 (本项目起步阶段用, 真实场景应从 admin 后台配置):
- menu_ready: 菜单已生成
- expiring_soon: 冰箱临期提醒
- low_stock: 库存不足提醒

如果未来要长期订阅, 需要在微信后台申请 + 审核, 把 persistent 改 true 即可
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.subscribe_message import SubscribeMessage
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.subscribe import (
    SubscribeGrantIn,
    SubscribeStatusOut,
    SubscribeTemplate,
    SubscribeTemplateListOut,
)

router = APIRouter(prefix="/subscribe", tags=["订阅消息"])

# 写死一批模板; 后续进 admin 后台管理
TEMPLATES: list[SubscribeTemplate] = [
    SubscribeTemplate(
        template_id="menu_ready_v1",
        title="菜单已生成",
        description="AI 算好菜单后通知您查看",
        keywords=["菜品", "日期"],
        trigger="每次生成菜单完成后",
    ),
    SubscribeTemplate(
        template_id="expiring_soon_v1",
        title="冰箱临期提醒",
        description="食材临期前 3 天提醒您优先吃",
        keywords=["食材", "到期日"],
        trigger="每日 08:00 扫描后",
    ),
    SubscribeTemplate(
        template_id="low_stock_v1",
        title="库存不足",
        description="做今晚菜单时发现某食材不够了",
        keywords=["食材", "缺口"],
        trigger="今晚菜单生成后",
    ),
]


@router.get("/templates", response_model=SuccessResponse)
async def list_templates():
    """小程序「我的 → 订阅」页加载时拉这个列表"""
    return SuccessResponse(
        code=0,
        message="success",
        data=SubscribeTemplateListOut(items=TEMPLATES).model_dump(),
    )


@router.post("/grant", response_model=SuccessResponse)
async def grant_subscribe(
    data: SubscribeGrantIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """记录用户授权 / 撤授权结果

    实际授权由前端 Taro.requestSubscribeMessage 完成; 这里只存结果
    """
    template = next((t for t in TEMPLATES if t.template_id == data.template_id), None)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在",
        )

    now = datetime.utcnow()
    result = await db.execute(
        select(SubscribeMessage).where(
            SubscribeMessage.user_id == user.id,
            SubscribeMessage.template_id == data.template_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        record = SubscribeMessage(
            user_id=user.id,
            template_id=data.template_id,
        )
        db.add(record)

    if data.grant and data.accepted == "accept":
        record.granted_at = now
        record.last_declined_at = None
    elif data.accepted in ("deny", "ban"):
        record.last_declined_at = now

    await db.commit()
    return SuccessResponse(code=0, message="已记录")


@router.get("/status/{template_id}", response_model=SuccessResponse)
async def get_status(
    template_id: str = Path(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查某模板用户授权状态 (UI 显示"已订阅 / 未订阅 / 已拒绝")"""
    result = await db.execute(
        select(SubscribeMessage).where(
            SubscribeMessage.user_id == user.id,
            SubscribeMessage.template_id == template_id,
        )
    )
    record: Optional[SubscribeMessage] = result.scalar_one_or_none()
    if not record:
        return SuccessResponse(
            code=0,
            message="success",
            data=SubscribeStatusOut(
                template_id=template_id,
                granted=False,
            ).model_dump(),
        )
    # 用户主动撤授权: 看 last_declined_at 在 granted_at 之后视为不再订阅
    granted = bool(record.granted_at) and (
        not record.last_declined_at or record.last_declined_at < record.granted_at
    )
    return SuccessResponse(
        code=0,
        message="success",
        data=SubscribeStatusOut(
            template_id=template_id,
            granted=granted,
            last_send_at=record.last_send_at.isoformat() if record.last_send_at else None,
            last_declined_at=record.last_declined_at.isoformat() if record.last_declined_at else None,
        ).model_dump(),
    )
