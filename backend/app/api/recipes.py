"""菜品库 API —— 富集缺口的查看与手动触发

为什么要有手动触发: 定时任务凌晨才跑, 但运营导入一批新菜之后想立刻补齐字段,
总不能让人等到第二天。这里就是那个"立刻跑一次"的口子。

为什么不用鉴权: 菜谱库是公共数据, 不含任何用户隐私。但富集会真金白银调 LLM,
所以默认关着, 且 limit 有上限 —— 开着的时候谁都能点, 就要靠 limit 兜住账单。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.schemas.common import SuccessResponse
from app.services.recipe_enrich_service import RecipeEnrichService

router = APIRouter(prefix="/recipes", tags=["菜品库"])


@router.get("/gaps", response_model=SuccessResponse)
async def get_gaps(db: AsyncSession = Depends(get_db)):
    """菜品库各字段的缺失数量 —— 定时任务"要不要跑"的依据, 也是数据健康度看板"""
    service = RecipeEnrichService(db)
    gaps = await service.count_gaps()
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "gaps": gaps,
            "enrich_enabled": get_settings().dish_enrich.enabled,
            "usable": service.usable,
        },
    )


@router.post("/enrich", response_model=SuccessResponse)
async def run_enrich(
    kind: str = Query("fields", pattern="^(fields|steps|expand)$"),
    limit: Optional[int] = Query(None, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """手动跑一次富集

    kind: fields=补字段 / steps=写做法 / expand=补新菜
    未启用 dish_enrich 时返回 degraded=true 且不打电话 —— 和线上定时任务行为一致,
    免得"点了一下没反应"变成谜题。
    """
    service = RecipeEnrichService(db)
    if kind == "steps":
        outcome = await service.enrich_steps(limit)
    elif kind == "expand":
        outcome = await service.expand(limit)
    else:
        outcome = await service.enrich_fields(limit)
    return SuccessResponse(
        code=0,
        message="success" if not outcome.degraded else "dish_enrich 未启用, 未调用模型",
        data=outcome.to_dict(),
    )


@router.get("/enrich/logs", response_model=SuccessResponse)
async def get_enrich_logs(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """最近几次富集做了什么 —— 无人值守的任务必须能事后查账"""
    from sqlalchemy import select

    from app.models.recipe import RecipeEnrichLog

    rows = (
        await db.execute(
            select(RecipeEnrichLog).order_by(RecipeEnrichLog.id.desc()).limit(limit)
        )
    ).scalars().all()
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "items": [
                {
                    "dish_name": r.dish_name,
                    "kind": r.kind,
                    "status": r.status,
                    "provider": r.provider,
                    "fields": r.fields,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        },
    )
