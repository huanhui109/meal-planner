"""F1 用户偏好管理 API - 所有读写都限定在当前登录用户"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.preference import (
    AllergyResponse,
    AllergyUpdate,
    BudgetResponse,
    BudgetUpdate,
    DietPreferenceResponse,
    DietPreferenceUpdate,
    HealthGoalResponse,
    HealthGoalUpdate,
    HouseholdResponse,
    HouseholdUpdate,
)
from app.services.preference_service import PreferenceService

router = APIRouter(prefix="/preferences", tags=["偏好管理"])

RESPONSE_SCHEMAS = {
    "HouseholdResponse": HouseholdResponse,
    "DietPreferenceResponse": DietPreferenceResponse,
    "AllergyResponse": AllergyResponse,
    "HealthGoalResponse": HealthGoalResponse,
    "BudgetResponse": BudgetResponse,
}


@router.get("/household", response_model=SuccessResponse)
async def get_household(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """未配置时返回 data=null, 前端据此展示空表单"""
    entity = await PreferenceService(db).get_household(user.id)
    return SuccessResponse(
        code=0,
        message="success",
        data=_dump(entity, "HouseholdResponse"),
    )


@router.put("/household", response_model=SuccessResponse)
async def update_household(
    data: HouseholdUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entity = await PreferenceService(db).update_household(user.id, data)
    await db.flush()
    return SuccessResponse(code=0, message="已保存", data=_dump(entity, "HouseholdResponse"))


@router.get("/diet", response_model=SuccessResponse)
async def get_diet(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    entity = await PreferenceService(db).get_diet_preference(user.id)
    return SuccessResponse(code=0, message="success", data=_dump(entity, "DietPreferenceResponse"))


@router.put("/diet", response_model=SuccessResponse)
async def update_diet(
    data: DietPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entity = await PreferenceService(db).update_diet_preference(user.id, data)
    await db.flush()
    return SuccessResponse(code=0, message="已保存", data=_dump(entity, "DietPreferenceResponse"))


@router.get("/allergy", response_model=SuccessResponse)
async def get_allergy(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    entity = await PreferenceService(db).get_allergy(user.id)
    return SuccessResponse(code=0, message="success", data=_dump(entity, "AllergyResponse"))


@router.put("/allergy", response_model=SuccessResponse)
async def update_allergy(
    data: AllergyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entity = await PreferenceService(db).update_allergy(user.id, data)
    await db.flush()
    return SuccessResponse(code=0, message="已保存", data=_dump(entity, "AllergyResponse"))


@router.get("/health-goal", response_model=SuccessResponse)
async def get_health_goal(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    entity = await PreferenceService(db).get_health_goal(user.id)
    return SuccessResponse(code=0, message="success", data=_dump(entity, "HealthGoalResponse"))


@router.put("/health-goal", response_model=SuccessResponse)
async def update_health_goal(
    data: HealthGoalUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entity = await PreferenceService(db).update_health_goal(user.id, data)
    await db.flush()
    return SuccessResponse(code=0, message="已保存", data=_dump(entity, "HealthGoalResponse"))


@router.get("/budget", response_model=SuccessResponse)
async def get_budget(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    entity = await PreferenceService(db).get_budget(user.id)
    return SuccessResponse(code=0, message="success", data=_dump(entity, "BudgetResponse"))


@router.put("/budget", response_model=SuccessResponse)
async def update_budget(
    data: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entity = await PreferenceService(db).update_budget(user.id, data)
    await db.flush()
    return SuccessResponse(code=0, message="已保存", data=_dump(entity, "BudgetResponse"))


@router.get("/summary", response_model=SuccessResponse)
async def get_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """一次性返回全部偏好, 供前端表单初始化"""
    summary = await PreferenceService(db).get_summary(user.id)
    return SuccessResponse(code=0, message="success", data=summary.model_dump())


def _dump(entity, schema_name: str):
    """ORM -> dict (None 表示尚未配置)"""
    if entity is None:
        return None
    schema = RESPONSE_SCHEMAS[schema_name]
    return schema.model_validate(entity).model_dump()
