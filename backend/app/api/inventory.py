"""F5 库存管理 API"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_current_user, get_db
from app.models.fridge_inventory import FridgeInventory
from app.models.ingredient import Ingredient
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.inventory import InventoryCreate
from app.services.activity_service import (
    CHANNEL_VISION,
    KIND_VISION_RECOGNIZE,
    ActivityService,
)
from app.services.inventory_service import InventoryService
from app.services.vision_service import VisionError, VisionService

router = APIRouter(prefix="/inventory", tags=["库存管理"])

EXPIRING_SOON_DAYS = 3


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiry_date 需为 YYYY-MM-DD 格式",
        ) from None


def _serialize(item: FridgeInventory, ingredient_name: str, category: str | None) -> dict:
    today = date.today()
    days_left = (item.expiry_date - today).days if item.expiry_date else None
    return {
        "id": item.id,
        "ingredient_id": item.ingredient_id,
        "ingredient_name": ingredient_name,
        "category": category,
        "quantity": item.quantity,
        "unit": item.unit,
        "purchase_date": str(item.purchase_date) if item.purchase_date else None,
        "expiry_date": str(item.expiry_date) if item.expiry_date else None,
        "days_left": days_left,
        "expiring_soon": days_left is not None and days_left <= EXPIRING_SOON_DAYS,
        "source": item.source,
    }


@router.get("", response_model=SuccessResponse)
async def list_inventory(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """当前库存 (临期优先展示)"""
    result = await db.execute(
        select(FridgeInventory, Ingredient.name, Ingredient.category)
        .join(Ingredient, Ingredient.id == FridgeInventory.ingredient_id)
        .where(FridgeInventory.user_id == user.id)
        .order_by(
            FridgeInventory.expiry_date.is_(None),
            FridgeInventory.expiry_date.asc(),
            FridgeInventory.id.asc(),
        )
    )
    rows = result.all()
    items = [_serialize(item, name, category) for item, name, category in rows]
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "total": len(items),
            "expiring_count": sum(1 for item in items if item["expiring_soon"]),
            "items": items,
        },
    )


@router.post("", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED)
async def add_inventory_item(
    data: InventoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动入库"""
    service = InventoryService(db)
    item = await service.add_item(
        user_id=user.id,
        ingredient_name=data.ingredient_name,
        quantity=data.quantity,
        unit=data.unit,
        expiry_date=_parse_date(data.expiry_date),
        source=data.source,
    )
    ingredient = await db.get(Ingredient, item.ingredient_id)
    return SuccessResponse(
        code=0,
        message="添加成功",
        data=_serialize(
            item, ingredient.name if ingredient else "", ingredient.category if ingredient else None
        ),
    )


@router.delete("/{item_id}", response_model=SuccessResponse)
async def delete_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除库存项"""
    deleted = await InventoryService(db).delete_item(item_id, user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="库存项不存在")
    return SuccessResponse(code=0, message="已删除")


@router.get("/expiring", response_model=SuccessResponse)
async def list_expiring(
    days: int = EXPIRING_SOON_DAYS,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """临期食材"""
    rows = await InventoryService(db).get_expiring_items(user.id, days)
    items = []
    for item in rows:
        ingredient = await db.get(Ingredient, item.ingredient_id)
        items.append(
            _serialize(
                item, ingredient.name if ingredient else "", ingredient.category if ingredient else None
            )
        )
    return SuccessResponse(code=0, message="success", data={"total": len(items), "items": items})


@router.post("/recognize", response_model=SuccessResponse)
async def recognize_inventory(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拍照识别: 返回候选食材清单, 不落库; 用户确认后再逐条走 POST /inventory

    没有配置视觉模型时返回 503 (而不是 500): 前端据此把按钮置灰并引导手动添加。
    """
    settings = get_settings()
    service = VisionService(settings)
    if not service.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务端还没有配置视觉模型, 可以先手动添加食材",
        )

    activity = ActivityService(db)
    limit = int(settings.llm.vision.daily_limit)
    used = await activity.count_today(user.id, KIND_VISION_RECOGNIZE)
    if limit > 0 and used >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今天已经识别 {used} 次, 上限 {limit} 次, 明天再来或手动添加吧",
        )

    image = await file.read()
    try:
        result = await service.recognize(image, file.content_type or "")
    except VisionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    await _match_known_ingredients(db, result["items"])
    await activity.log(
        user.id,
        channel=CHANNEL_VISION,
        kind=KIND_VISION_RECOGNIZE,
        title=f"拍照识别出 {len(result['items'])} 样食材",
        detail=file.filename or None,
    )
    return SuccessResponse(
        code=0,
        message="识别完成",
        data={
            **result,
            "used_today": used + 1,
            "daily_limit": limit,
        },
    )


async def _match_known_ingredients(db: AsyncSession, items: list) -> None:
    """把识别出的名字对到食材库, 前端据此提示"新食材"与自动分类"""
    names = [item["name"] for item in items if item.get("name")]
    if not names:
        return
    result = await db.execute(
        select(Ingredient.name, Ingredient.id, Ingredient.category, Ingredient.standard_unit).where(
            Ingredient.name.in_(names)
        )
    )
    known = {name: (ingredient_id, category, unit) for name, ingredient_id, category, unit in result.all()}
    for item in items:
        hit = known.get(item["name"])
        if hit:
            item["ingredient_id"] = hit[0]
            item["known"] = True
            item["category"] = hit[1] or item["category"]
            item["unit"] = item["unit"] or hit[2] or ""
        else:
            item["ingredient_id"] = None
            item["known"] = False
