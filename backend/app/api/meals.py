from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.meal import MealActionRequest, MealContextPatch, MealProposeRequest, MealSlotName
from app.services.meal_service import MealService

router = APIRouter(prefix="/meals", tags=["这一餐"])


@router.get("/current", response_model=SuccessResponse)
async def current_meal(
    meal_slot: Optional[MealSlotName] = None, meal_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).current(
        user.id, MealContextPatch(meal_slot=meal_slot, meal_date=meal_date),
    ))


@router.post("/propose", response_model=SuccessResponse)
async def propose_meal(
    payload: MealProposeRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).propose(
        user.id, payload.context, payload.expected_revision,
    ))


@router.get("/history", response_model=SuccessResponse)
async def meal_history(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).history(user.id, limit))


@router.post("/{proposal_id}/viewed", response_model=SuccessResponse)
async def view_meal(
    proposal_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    await MealService(db).record_view(user.id, proposal_id)
    return SuccessResponse(data={"recorded": True})


@router.post("/{proposal_id}/accept", response_model=SuccessResponse)
async def accept_meal(
    proposal_id: str, payload: MealActionRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).action(
        user.id, proposal_id, "accept", payload.expected_revision,
    ))


@router.post("/{proposal_id}/complete", response_model=SuccessResponse)
async def complete_meal(
    proposal_id: str, payload: MealActionRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).action(
        user.id, proposal_id, "complete", payload.expected_revision, payload.deduct_inventory,
    ))


@router.post("/{proposal_id}/undo", response_model=SuccessResponse)
async def undo_meal(
    proposal_id: str, payload: MealActionRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await MealService(db).action(
        user.id, proposal_id, "undo", payload.expected_revision,
    ))
