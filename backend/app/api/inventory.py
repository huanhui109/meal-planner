"""F5 库存管理 API"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.fridge_inventory import FridgeInventory
from app.models.ingredient import Ingredient
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.inventory import InventoryCreate
from app.services.inventory_service import InventoryService

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
        )


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
async def list_inventory(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
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
        data=_serialize(item, ingredient.name if ingredient else "", ingredient.category if ingredient else None),
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
        items.append(_serialize(item, ingredient.name if ingredient else "", ingredient.category if ingredient else None))
    return SuccessResponse(code=0, message="success", data={"total": len(items), "items": items})
