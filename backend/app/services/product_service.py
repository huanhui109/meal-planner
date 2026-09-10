"""商品管理服务"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_products(self, products: List[dict]) -> int:
        """批量 upsert 商品"""
        count = 0
        for p in products:
            existing = await self.db.execute(
                select(Product).where(
                    Product.source_platform == p.get("platform", "xiaoxiang"),
                    Product.sku_id == p.get("sku_id"),
                )
            )
            item = existing.scalar_one_or_none()
            if item:
                old_price = item.price
                item.price = p.get("price", 0)
                item.is_active = p.get("is_active", True)
                item.in_stock = p.get("in_stock", True)
                if abs(item.price - old_price) / max(old_price, 0.01) > 0.2:
                    item.price_changed = True
            else:
                item = Product(
                    source_platform=p.get("platform", "xiaoxiang"),
                    sku_id=p.get("sku_id", ""),
                    name=p.get("name", ""),
                    category=p.get("category", ""),
                    price=p.get("price", 0),
                    unit=p.get("unit", ""),
                )
                self.db.add(item)
            count += 1
        await self.db.flush()
        return count

    async def get_products(self, category: Optional[str] = None) -> List[Product]:
        """获取商品列表"""
        query = select(Product).where(Product.is_active.is_(True))
        if category:
            query = query.where(Product.category == category)
        result = await self.db.execute(query)
        return list(result.scalars().all())
