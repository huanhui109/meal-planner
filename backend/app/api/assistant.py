from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.assistant_bridge import AssistantAdjustmentRequest
from app.schemas.common import SuccessResponse
from app.schemas.meal import AssistantGrantRequest, AssistantSaveRequest, MealContextPatch, MealSlotName
from app.services.assistant_adjustment_service import AssistantAdjustmentService
from app.services.assistant_service import AssistantService
from app.services.meal_service import MealService
from app.services.workbuddy_client import WorkBuddyClient, WorkBuddyError, get_workbuddy_client
from app.services.workbuddy_service import WorkBuddyService


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/assistant", tags=["饭决 Skill"], dependencies=[Depends(no_store)])


@router.get("/skill.zip")
async def download_skill(user: User = Depends(get_current_user)):
    root = Path(__file__).resolve().parents[3] / "skills" / "fandecide"
    files = ("SKILL.md", "scripts/fandecide.py")
    if not all((root / file).is_file() for file in files):
        from fastapi import HTTPException

        raise HTTPException(503, "Skill 安装包暂不可用，请从项目 skills/fandecide 目录获取")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(root / file, f"fandecide/{file}")
    return Response(
        output.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="fandecide.zip"'},
    )


async def assistant_user(request: Request, db: AsyncSession = Depends(get_db)) -> int:
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return await AssistantService(db).authenticate(token)


@router.get("/grants", response_model=SuccessResponse)
async def list_grants(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await AssistantService(db).list(user.id))


@router.post("/grants", response_model=SuccessResponse)
async def create_grant(
    payload: AssistantGrantRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return SuccessResponse(data=await AssistantService(db).create(user.id, payload.name))


@router.delete("/grants/{grant_id}", response_model=SuccessResponse)
async def revoke_grant(
    grant_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    await AssistantService(db).revoke(user.id, grant_id)
    return SuccessResponse(data={"revoked": True})


@router.post("/context", response_model=SuccessResponse)
async def assistant_context(
    payload: MealContextPatch,
    db: AsyncSession = Depends(get_db), user_id: int = Depends(assistant_user),
):
    return SuccessResponse(data=await MealService(db).assistant_context(user_id, payload))


@router.post("/proposals", response_model=SuccessResponse)
async def save_assistant_proposal(
    payload: AssistantSaveRequest,
    db: AsyncSession = Depends(get_db), user_id: int = Depends(assistant_user),
):
    return SuccessResponse(data=await MealService(db).propose(
        user_id, payload.context, payload.expected_revision, payload.candidate_keys, payload.reason,
    ))


@router.get("/workbuddy")
async def workbuddy_status(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    return SuccessResponse(data=await WorkBuddyService(db, client).status(user.id))


@router.post("/workbuddy/authorize")
async def authorize_workbuddy(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    return SuccessResponse(data={"url": await WorkBuddyService(db, client).authorize(user.id)})


@router.get("/workbuddy/callback")
async def workbuddy_callback(
    state: str = Query(default="", max_length=200), code: str = Query(default="", max_length=2048),
    error: str = Query(default="", max_length=200),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    outcome = "connected"
    try:
        await WorkBuddyService(db, client).callback(user.id, state, code, error)
    except (WorkBuddyError, HTTPException):
        outcome = "failed"
    return RedirectResponse(
        f"/me?workbuddy={outcome}#assistant", status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.delete("/workbuddy")
async def disconnect_workbuddy(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    await WorkBuddyService(db, client).disconnect(user.id)
    return SuccessResponse(data={"disconnected": True})


@router.post("/adjustments")
async def start_adjustment(
    payload: AssistantAdjustmentRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    return SuccessResponse(data=await AssistantAdjustmentService(db, client).start(user.id, payload))


@router.get("/adjustments/current")
async def current_adjustment(
    meal_slot: MealSlotName | None = None, meal_date: date | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    patch = MealContextPatch.model_validate({
        key: value for key, value in {"meal_slot": meal_slot, "meal_date": meal_date}.items() if value is not None
    })
    return SuccessResponse(data=await AssistantAdjustmentService(db, client).current(user.id, patch))


@router.get("/adjustments/{job_id}")
async def poll_adjustment(
    job_id: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    return SuccessResponse(data=await AssistantAdjustmentService(db, client).poll(user.id, job_id))


@router.post("/adjustments/{job_id}/cancel")
async def cancel_adjustment(
    job_id: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
):
    return SuccessResponse(data=await AssistantAdjustmentService(db, client).cancel(user.id, job_id))
