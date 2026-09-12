"""F3 商品管理 API - 数据来自二期采集, 当前仅提供查询"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["商品管理"])


@router.get("", response_model=SuccessResponse)
async def list_products(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """商品列表 (共享数据, 仅要求登录)"""
    products = await ProductService(db).get_products(category)
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "total": len(products),
            "items": [
                {
                    "id": product.id,
                    "name": product.name,
                    "category": product.category,
                    "price": product.price,
                    "unit": product.unit,
                    "in_stock": product.in_stock,
                    "price_changed": product.price_changed,
                }
                for product in products
            ],
        },
    )


@router.get("/search", response_model=SuccessResponse)
async def search_products(
    ingredient: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按食材名模糊搜索商品 (audit T4.1 V3.0)

    数据来自 Scraper 定时抓取, 平台真实接入前返回空数组
    """
    products = await ProductService(db).search_by_ingredient(ingredient)
    return SuccessResponse(
        code=0,
        message="success",
        data={
            "ingredient": ingredient,
            "total": len(products),
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "category": p.category,
                    "price": p.price,
                    "unit": p.unit,
                    "in_stock": p.in_stock,
                    "price_changed": p.price_changed,
                    "platform": p.source_platform,
                }
                for p in products
            ],
            "v3_status": "stub data only - real scraping pending",
        },
    )
