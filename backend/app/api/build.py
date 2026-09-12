"""F6 构建元信息 API - 启动期版本检测

GET /api/build-info 返回最新版本与最低版本要求

不需鉴权: 这条接口要在登录前就拿到, 否则用户拿不到强制更新就登录卡死
返回空表时也不报错: 用代码默认值兜底 (0.5.0 / 0.5.0 / 不强制)
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.dependencies import get_db
from app.models.build_info import BuildInfo
from app.schemas.build import BuildInfoOut
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/build-info", tags=["构建"])

# 兜底默认: 兜住 build_info 表还没数据 / 后端未配置的情况
DEFAULT = BuildInfoOut(
    latest_version="0.5.0",
    min_version="0.5.0",
    force_update=False,
    update_url=None,
    notes=None,
)


@router.get("", response_model=SuccessResponse)
async def get_build_info(db: AsyncSession = Depends(get_db)):
    """小程序启动期拉版本元信息

    取最新一条 (按 released_at 倒序) 作为 latest; 任意一条 force_update=true 就拒服
    """
    result = await db.execute(
        select(BuildInfo).order_by(BuildInfo.released_at.desc()).limit(5)
    )
    rows = result.scalars().all()
    if not rows:
        return SuccessResponse(code=0, message="success", data=DEFAULT.model_dump())

    latest = rows[0]
    payload = BuildInfoOut(
        latest_version=latest.version,
        min_version=latest.min_version,
        force_update=latest.force_update,
        update_url=latest.update_url,
        notes=latest.notes,
    )
    return SuccessResponse(code=0, message="success", data=payload.model_dump())
