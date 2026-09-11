"""F2 菜单生成与管理 API"""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_current_user, get_db
from app.models.budget import Budget
from app.models.health_goal import HealthGoal
from app.models.menu import Menu, MenuGenerationTask, MenuItem
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.menu import GenerateAcceptedResponse, GenerationTaskResponse
from app.schemas.recipe import MenuGenerateRequest, MenuItemReplaceRequest
from app.services.deeplink_service import PLATFORM_XIAOXIANG
from app.services.generation_service import GenerationError, count_today_tasks, create_generation_task
from app.services.inventory_service import InventoryService
from app.services.menu_service import MenuService, week_start_of
from app.services.order_service import OrderService
from app.services.replacement_service import ReplacementQuotaExceeded, ReplacementService
from app.services.shopping_service import ShoppingService

router = APIRouter(prefix="/menus", tags=["菜单管理"])


def _parse_week_start(request: MenuGenerateRequest) -> date:
    raw = request.week_start_date or request.week_start
    if not raw:
        return week_start_of()
    try:
        return week_start_of(date.fromisoformat(raw.strip()))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="week_start 需为 YYYY-MM-DD 格式",
        ) from None


async def _load_profile(db: AsyncSession, user_id: int) -> Tuple[Optional[HealthGoal], Optional[Budget]]:
    goal = (await db.execute(select(HealthGoal).where(HealthGoal.user_id == user_id))).scalar_one_or_none()
    budget = (await db.execute(select(Budget).where(Budget.user_id == user_id))).scalar_one_or_none()
    return goal, budget


async def _require_menu(db: AsyncSession, menu_id: int, user_id: int) -> Menu:
    menu = await MenuService(db).get_menu(menu_id, user_id)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单不存在")
    return menu


async def _require_item(db: AsyncSession, menu: Menu, item_id: int) -> MenuItem:
    for item in menu.menu_items:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单项不存在")


@router.post("/generate", response_model=SuccessResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_menu(
    request: MenuGenerateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交生成任务; 同一周已有草稿时直接复用, 不重复消耗 LLM 额度"""
    settings = get_settings()
    week_start = _parse_week_start(request)
    service = MenuService(db)

    if not request.force:
        existing = await service.get_editable_menu_for_week(user.id, week_start)
        if existing:
            response.status_code = status.HTTP_200_OK
            return SuccessResponse(
                code=0,
                message="该周已有菜单, 直接复用",
                data=GenerateAcceptedResponse(
                    task_id=None,
                    menu_id=existing.id,
                    week_start_date=str(existing.week_start_date),
                    reused=True,
                    status=existing.status,
                ).model_dump(),
            )

    # 首次生成和重新生成走各自的额度: 重生成是常规编辑动作, 不该被 3 次/天的探索额度卡住
    is_regeneration = bool(request.force)
    limit = settings.menu.daily_regenerate_limit if is_regeneration else settings.menu.daily_generation_limit
    used = await count_today_tasks(db, user.id, is_regeneration)
    if used >= limit:
        action = "重新生成" if is_regeneration else "生成"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日{action}次数已用尽 ({used}/{limit}), 请明天再试",
        )

    task = await create_generation_task(
        db,
        user_id=user.id,
        week_start=week_start,
        payload={"week_start": str(week_start), "force": request.force},
        is_regeneration=is_regeneration,
    )
    return SuccessResponse(
        code=0,
        message="已提交生成任务",
        data=GenerateAcceptedResponse(
            task_id=task.id,
            menu_id=None,
            week_start_date=str(week_start),
            reused=False,
            status=task.status,
        ).model_dump(),
    )


@router.get("/generation-tasks/{task_id}", response_model=SuccessResponse)
async def get_generation_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """轮询生成任务状态"""
    task = (
        await db.execute(
            select(MenuGenerationTask).where(
                MenuGenerationTask.id == task_id, MenuGenerationTask.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return SuccessResponse(
        code=0,
        message="success",
        data=GenerationTaskResponse(
            task_id=task.id,
            status=task.status,
            menu_id=task.menu_id,
            week_start_date=str(task.week_start_date),
            error=task.error,
            created_at=task.created_at.isoformat() if task.created_at else None,
            finished_at=task.finished_at.isoformat() if task.finished_at else None,
        ).model_dump(),
    )


@router.get("/current", response_model=SuccessResponse)
async def get_current_menu(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前进行中的菜单 (含菜品、成本、营养与预算校验)"""
    service = MenuService(db)
    menu = await service.get_current_menu(user.id)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="暂无菜单")
    goal, budget = await _load_profile(db, user.id)
    return SuccessResponse(code=0, message="success", data=await service.serialize(menu, goal, budget))


@router.get("/{menu_id}", response_model=SuccessResponse)
async def get_menu(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """菜单详情"""
    menu = await _require_menu(db, menu_id, user.id)
    goal, budget = await _load_profile(db, user.id)
    return SuccessResponse(
        code=0,
        message="success",
        data=await MenuService(db).serialize(menu, goal, budget),
    )


@router.post("/{menu_id}/confirm", response_model=SuccessResponse)
async def confirm_menu(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """确认本周菜单"""
    menu = await _require_menu(db, menu_id, user.id)
    await MenuService(db).confirm(menu)
    return SuccessResponse(code=0, message="已确认菜单", data={"menu_id": menu.id, "status": menu.status})


@router.get("/{menu_id}/order-suggestion", response_model=SuccessResponse)
async def get_order_suggestion(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """补单建议 (采购页复用): 缺什么、大概多少钱、够不够起送价"""
    await _require_menu(db, menu_id, user.id)
    shopping = await ShoppingService(db).build(menu_id, user.id)
    suggestion = OrderService().build_suggestion(shopping, platform=PLATFORM_XIAOXIANG)
    return SuccessResponse(code=0, message="success", data=suggestion)


@router.get("/{menu_id}/shopping-list", response_model=SuccessResponse)
async def get_shopping_list(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """采购清单: 菜单所需与冰箱库存的差集"""
    data = await ShoppingService(db).build(menu_id, user.id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单不存在")
    return SuccessResponse(code=0, message="success", data=data)


@router.put("/{menu_id}/items/{item_id}/replace", response_model=SuccessResponse)
async def replace_menu_item(
    menu_id: int,
    item_id: int,
    request: Optional[MenuItemReplaceRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """换一道: 先从本地菜谱库挑一道, 挑不到再降级让 AI 生成一道

    请求体三种用法: 留空走自动; 传 recipe_id 直接还原 (「换回上一道」);
    传 recipe_name 走旧的手动指定路径。
    """
    # 先取成普通 int: 走 AI 降级时服务里会结束当前事务把连接还池, ORM 对象会被过期,
    # 之后再读 user.id 就会触发同步懒加载 (异步会话里直接 MissingGreenlet)。
    user_id = user.id
    menu = await _require_menu(db, menu_id, user_id)
    item = await _require_item(db, menu, item_id)
    try:
        result = await ReplacementService(db).replace(menu, item, user_id, request)
    except ReplacementQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    goal, budget = await _load_profile(db, user_id)
    data = await MenuService(db).serialize(result.menu, goal, budget)
    data["replacement"] = {
        "source": result.source,
        "recipe_id": result.recipe.id if result.recipe else None,
        "recipe_name": result.recipe.name if result.recipe else None,
    }
    message = {
        "local": "已从本地菜谱库换好",
        "ai": "AI 已生成新菜并换好",
        "restore": "已换回上一道",
        "manual": "已替换",
    }.get(result.source, "已替换")
    return SuccessResponse(
        code=0,
        message=message,
        data=data,
    )


@router.put("/{menu_id}/items/{item_id}/lock", response_model=SuccessResponse)
async def lock_menu_item(
    menu_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """锁定某餐次 (锁定后不参与后续重生成)"""
    menu = await _require_menu(db, menu_id, user.id)
    item = await _require_item(db, menu, item_id)
    await MenuService(db).set_locked(item, True)
    return SuccessResponse(code=0, message="已锁定", data={"item_id": item.id, "is_locked": True})


@router.put("/{menu_id}/items/{item_id}/unlock", response_model=SuccessResponse)
async def unlock_menu_item(
    menu_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """解锁某餐次"""
    menu = await _require_menu(db, menu_id, user.id)
    item = await _require_item(db, menu, item_id)
    await MenuService(db).set_locked(item, False)
    return SuccessResponse(code=0, message="已解锁", data={"item_id": item.id, "is_locked": False})


@router.put("/{menu_id}/items/{item_id}/cooked", response_model=SuccessResponse)
async def mark_menu_item_cooked(
    menu_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """标记已做: 按菜谱用量扣减库存并写入消耗记录"""
    menu = await _require_menu(db, menu_id, user.id)
    item = await _require_item(db, menu, item_id)
    if item.is_cooked:
        return SuccessResponse(
            code=0,
            message="该餐次已标记完成",
            data={"item_id": item.id, "already_cooked": True, "consumed": [], "missing": []},
        )
    result = await InventoryService(db).consume_by_menu_item(item.id, user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单项不存在")
    return SuccessResponse(
        code=0,
        message="已标记完成并扣减库存",
        data={
            "item_id": item.id,
            "already_cooked": result.already_cooked,
            "consumed": result.consumed,
            "missing": result.missing,
        },
    )


@router.delete("/{menu_id}/items/{item_id}/cooked", response_model=SuccessResponse)
async def undo_menu_item_cooked(
    menu_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """撤销「标记已做」: 库存加回去, 并删掉这次产生的消耗流水

    前端在标记后给 5 秒的撤销窗口 —— 误触是高频错误, 让用户自己回头改
    比任何二次确认都省事。
    """
    menu = await _require_menu(db, menu_id, user.id)
    item = await _require_item(db, menu, item_id)
    result = await InventoryService(db).restore_by_menu_item(item.id, user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单项不存在")
    return SuccessResponse(
        code=0,
        message="已撤销, 库存已还原",
        data={"item_id": result["item_id"], "restored": result["restored"], "skipped": result["skipped"]},
    )
