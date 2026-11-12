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
from app.schemas.assistant_bridge import (
    AssistantAdjustmentRequest,
    CandidateRequest,
    LoginStartRequest,
    ModelChoiceRequest,
)
from app.schemas.common import SuccessResponse
from app.schemas.meal import AssistantGrantRequest, AssistantSaveRequest, MealContextPatch, MealSlotName
from app.services.assistant_adjustment_service import AssistantAdjustmentService
from app.services.assistant_service import AssistantService
from app.services.meal_service import MealService
from app.services.workbuddy_client import WorkBuddyClient, WorkBuddyError, get_workbuddy_client
from app.services.workbuddy_login_service import WorkBuddyLoginService, get_workbuddy_login_service
from app.services.workbuddy_model_catalog import ModelCatalogService
from app.services.workbuddy_model_client import (
    WorkBuddyModelClient,
    get_workbuddy_model_client,
)
from app.services.workbuddy_service import WorkBuddyService


def unified_service(
    db: AsyncSession,
    client: WorkBuddyClient,
    model: WorkBuddyModelClient,
) -> AssistantAdjustmentService:
    """Assemble the unified orchestrator from the two DI-provided clients.

    ``client`` (legacy official-OAuth WorkBuddyClient) is accepted only so the
    existing test fixture override keeps working; the unified path uses
    ``model`` (direct upstream call) exclusively.
    """
    return AssistantAdjustmentService(db, client=client, model=model)


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/assistant", tags=["饭决 Skill"], dependencies=[Depends(no_store)])


@router.get("/skill.zip")
async def download_skill(user: User = Depends(get_current_user)):
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    root = skills_root / "fandecide"
    # 候选菜品技能是应用内部调用的能力，随包下发规格与输出契约，便于审计与联调。
    candidates_root = skills_root / "fandecide-candidates"
    files = ("SKILL.md", "scripts/fandecide.py")
    if not all((root / file).is_file() for file in files):
        from fastapi import HTTPException

        raise HTTPException(503, "Skill 安装包暂不可用，请从项目 skills/fandecide 目录获取")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(root / file, f"fandecide/{file}")
        for file in ("SKILL.md", "contract.json"):
            path = candidates_root / file
            if path.is_file():
                archive.write(path, f"fandecide/candidates/{file}")
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


@router.get("/model")
async def model_status(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    """Unified direct-model connection status + the user's model choice."""
    status = await client.status()
    view = await ModelCatalogService(db, client).view(user.id)
    return SuccessResponse(data={
        **status,
        "model": view["effective"],
        "catalog": view["catalog"],
        "selected": view["selected"],
        "auto": view["auto"],
        "selection_available": view["selection_available"],
    })


@router.post("/model")
async def choose_model(
    payload: ModelChoiceRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    """Persist the user's model choice (empty id = auto)."""
    try:
        await ModelCatalogService(db, client).choose(user.id, payload.model, payload.region)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    view = await ModelCatalogService(db, client).view(user.id)
    return SuccessResponse(data={
        "selected": view["selected"], "effective": view["effective"], "auto": view["auto"],
    })


@router.post("/login")
async def start_login(
    payload: LoginStartRequest,
    login: WorkBuddyLoginService = Depends(get_workbuddy_login_service),
):
    """Start a browser/QR sign-in and return the URL the user opens."""
    return SuccessResponse(data=await login.start(payload.region, payload.base))


@router.get("/login/{login_id}")
async def poll_login(
    login_id: str, region: str = Query(default="", max_length=10),
    login: WorkBuddyLoginService = Depends(get_workbuddy_login_service),
):
    """Poll one sign-in. On success the credential is written to the vault."""
    return SuccessResponse(data=await login.poll(login_id, region))


@router.delete("/login")
async def logout(
    region: str = Query(default="", max_length=10),
    login: WorkBuddyLoginService = Depends(get_workbuddy_login_service),
):
    """Remove plugin-owned credential copies; the desktop app keeps its sign-in."""
    return SuccessResponse(data=await login.logout(region))


@router.post("/candidates", response_model=SuccessResponse)
async def dish_candidates(
    payload: CandidateRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    model: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    """应用内候选菜品技能：一次模型请求 → 默认 4 个（3-5）结构化候选。

    单跳、低延迟：不建任务、不轮询、不调选菜技能、不重试、不追问。
    ``persist`` 打开时仍由服务端按「不得杜撰」的全部校验裁决能否入池。
    规格见 skills/fandecide-candidates/SKILL.md。
    """
    from app.services.dish_candidate_service import DishCandidateService

    try:
        selected = (await ModelCatalogService(db, model).selected(user.id)).get("model", "")
    except Exception:  # noqa: BLE001 - a preference read must never block candidates
        selected = ""
    service = DishCandidateService(
        db, model, model=selected,
        timeout_seconds=float(model.settings.workbuddy.candidate_timeout_seconds),
    )
    result = await service.generate(
        payload.description,
        context=payload.context,
        count=payload.count,
        exclude_names=payload.exclude_names,
        named_dish=payload.named_dish,
        persist=payload.persist,
    )
    return SuccessResponse(data=result.as_dict())


@router.post("/adjustments")
async def start_adjustment(
    payload: AssistantAdjustmentRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    model: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    return SuccessResponse(data=await unified_service(db, client, model).start(user.id, payload))


@router.get("/adjustments/current")
async def current_adjustment(
    meal_slot: MealSlotName | None = None, meal_date: date | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    model: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    patch = MealContextPatch.model_validate({
        key: value for key, value in {"meal_slot": meal_slot, "meal_date": meal_date}.items() if value is not None
    })
    return SuccessResponse(data=await unified_service(db, client, model).current(user.id, patch))


@router.get("/adjustments/{job_id}")
async def poll_adjustment(
    job_id: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    model: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    return SuccessResponse(data=await unified_service(db, client, model).poll(user.id, job_id))


@router.post("/adjustments/{job_id}/cancel")
async def cancel_adjustment(
    job_id: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    client: WorkBuddyClient = Depends(get_workbuddy_client),
    model: WorkBuddyModelClient = Depends(get_workbuddy_model_client),
):
    return SuccessResponse(data=await unified_service(db, client, model).cancel(user.id, job_id))
