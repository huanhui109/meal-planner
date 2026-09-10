"""库存相关 Pydantic 模型"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class InventoryCreate(BaseModel):
    ingredient_name: str
    quantity: float
    unit: str
    expiry_date: Optional[str] = None
    source: str = "manual"


class InventoryUpdate(BaseModel):
    quantity: Optional[float] = None
    expiry_date: Optional[str] = None


class InventoryResponse(BaseModel):
    id: int
    ingredient_id: int
    ingredient_name: Optional[str] = None
    quantity: float
    unit: str
    purchase_date: Optional[str] = None
    expiry_date: Optional[str] = None
    source: Optional[str] = None

    class Config:
        from_attributes = True


class MissingIngredient(BaseModel):
    ingredient_name: str
    required_quantity: float
    unit: str
    in_stock_quantity: float
    deficit: float
