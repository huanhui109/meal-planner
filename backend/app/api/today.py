"""今日页 API - 一次请求拿到"今天该干什么" """

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.services.today_service import TodayService

router = APIRouter(prefix="/today", tags=["今日"])


@router.get("", response_model=SuccessResponse)
async def get_today(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """今日概览: 餐次 + 预算 + 采购缺口 + 补单建议 + 自做/外卖 + 流程时间线

    没有菜单也返回 200 (has_menu=False), 由前端显示"下一步"空状态,
    不用 404 —— 空状态是正常状态, 不是错误。
    """
    data = await TodayService(db).build(user.id)
    return SuccessResponse(code=0, message="success", data=data)


@router.post("/takeout-price", response_model=SuccessResponse)
async def remember_takeout_price(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """记住用户在卡片上改的外卖价, 下次默认就用它"""
    from app.schemas.preference import BudgetUpdate
    from app.services.preference_service import PreferenceService

    try:
        price = float(payload.get("price"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="price 需要是数字",
        ) from None
    if not (0 <= price <= 500):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="外卖参考价请填 0-500 之间的数字",
        )

    service = PreferenceService(db)
    existing = await service.get_budget(user.id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="还没有设置预算, 请先去「我的 → 目标与预算」填一下",
        )
    data = BudgetUpdate(
        weekday_daily_budget=existing.weekday_daily_budget,
        weekend_daily_budget=existing.weekend_daily_budget,
        weekly_cap=existing.weekly_cap,
        min_meal_budget=existing.min_meal_budget,
        takeout_reference_price=price,
    )
    updated = await service.update_budget(user.id, data)
    return SuccessResponse(
        code=0,
        message="已记住, 下次默认使用这个价",
        data={"takeout_reference_price": updated.takeout_reference_price},
    )
