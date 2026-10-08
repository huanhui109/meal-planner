"""库存相关 Pydantic 模型"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class InventoryCreate(BaseModel):
    ingredient_name: str
    quantity: float
    unit: str
    expiry_date: Optional[str] = None
    source: str = "manual"


class InventoryUpdate(BaseModel):
    quantity: Optional[float] = None
    expiry_date: Optional[str] = None


class InventoryBulkItem(BaseModel):
    ingredient_name: str
    quantity: float = 1
    unit: str = "份"


class InventoryBulkCreate(BaseModel):
    items: list[InventoryBulkItem]


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    ingredient_name: Optional[str] = None
    quantity: float
    unit: str
    purchase_date: Optional[str] = None
    expiry_date: Optional[str] = None
    source: Optional[str] = None


class MissingIngredient(BaseModel):
    ingredient_name: str
    required_quantity: float
    unit: str
    in_stock_quantity: float
    deficit: float
