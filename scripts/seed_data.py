"""种子数据导入 - 基础食材表与参考单价

前置条件: 已执行 alembic upgrade head (本脚本不再建表)。
用法: python scripts/seed_data.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app.database import async_session_factory, close_db, engine  # noqa: E402
from app.models.ingredient import Ingredient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")

# (名称, 分类, 标准单位, 参考单价 元/单位)
SEED_INGREDIENTS = [
    ("西红柿", "蔬菜", "个", 3.0),
    ("黄瓜", "蔬菜", "根", 2.5),
    ("土豆", "蔬菜", "个", 2.0),
    ("鸡蛋", "肉禽蛋", "个", 1.2),
    ("鸡胸肉", "肉禽蛋", "g", 0.025),
    ("五花肉", "肉禽蛋", "g", 0.032),
    ("牛肉", "肉禽蛋", "g", 0.06),
    ("虾仁", "水产", "g", 0.08),
    ("带鱼", "水产", "条", 15.0),
    ("豆腐", "蔬菜", "块", 3.0),
    ("白菜", "蔬菜", "颗", 6.0),
    ("菠菜", "蔬菜", "把", 4.0),
    ("胡萝卜", "蔬菜", "根", 1.5),
    ("洋葱", "蔬菜", "个", 2.0),
    ("青椒", "蔬菜", "个", 2.0),
    ("蒜", "调味品", "头", 3.0),
    ("姜", "调味品", "块", 2.0),
    ("葱", "调味品", "根", 1.0),
    ("大米", "主食", "g", 0.006),
    ("面粉", "主食", "g", 0.006),
    ("面条", "主食", "g", 0.008),
    ("牛奶", "乳制品", "ml", 0.012),
    ("酸奶", "乳制品", "瓶", 4.0),
    ("苹果", "水果", "个", 3.0),
    ("香蕉", "水果", "根", 2.0),
    ("食用油", "调味品", "ml", 0.012),
    ("盐", "调味品", "g", 0.003),
    ("酱油", "调味品", "ml", 0.01),
    ("醋", "调味品", "ml", 0.01),
    ("白糖", "调味品", "g", 0.008),
    ("料酒", "调味品", "ml", 0.008),
    ("蚝油", "调味品", "ml", 0.02),
    ("番茄酱", "调味品", "g", 0.02),
    ("豆瓣酱", "调味品", "g", 0.02),
    ("八角", "调味品", "个", 0.3),
    ("花椒", "调味品", "g", 0.08),
    ("猪肉馅", "肉禽蛋", "g", 0.03),
    ("排骨", "肉禽蛋", "g", 0.045),
    ("鸡翅", "肉禽蛋", "个", 3.5),
    ("鱼", "水产", "条", 20.0),
    ("生菜", "蔬菜", "颗", 4.0),
    ("茄子", "蔬菜", "个", 3.0),
    ("西蓝花", "蔬菜", "颗", 5.0),
    ("玉米", "蔬菜", "根", 3.0),
    ("豌豆", "蔬菜", "g", 0.012),
    ("木耳", "蔬菜", "g", 0.06),
    ("香菇", "蔬菜", "个", 1.5),
    ("虾皮", "调味品", "g", 0.05),
    ("红薯", "蔬菜", "个", 3.0),
    ("紫甘蓝", "蔬菜", "颗", 6.0),
    ("豆芽", "蔬菜", "g", 0.006),
    ("芹菜", "蔬菜", "根", 3.0),
    ("韭菜", "蔬菜", "把", 4.0),
    ("苦瓜", "蔬菜", "根", 4.0),
    ("丝瓜", "蔬菜", "根", 3.0),
    ("冬瓜", "蔬菜", "块", 4.0),
    ("南瓜", "蔬菜", "块", 5.0),
    ("辣椒", "蔬菜", "个", 1.0),
    ("黑胡椒", "调味品", "g", 0.08),
    ("孜然", "调味品", "g", 0.06),
    ("花生", "坚果", "g", 0.02),
    ("核桃", "坚果", "个", 1.5),
    ("芝麻", "调味品", "g", 0.03),
    ("酵母", "调味品", "g", 0.03),
    ("淀粉", "调味品", "g", 0.01),
    ("香菜", "调味品", "把", 2.0),
]


async def ensure_schema() -> None:
    """表不存在时给出可操作的提示, 而不是抛裸 SQL 错误"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM ingredient LIMIT 1"))
    except Exception:
        raise SystemExit(
            "数据表不存在, 请先执行: cd backend && python -m alembic upgrade head"
        ) from None


async def seed() -> None:
    await ensure_schema()
    created = updated = 0
    async with async_session_factory() as session:
        for name, category, unit, price in SEED_INGREDIENTS:
            existing = (
                await session.execute(select(Ingredient).where(Ingredient.name == name))
            ).scalar_one_or_none()
            if existing:
                existing.category = category
                existing.standard_unit = unit
                existing.reference_price = price
                updated += 1
            else:
                session.add(
                    Ingredient(
                        name=name,
                        category=category,
                        standard_unit=unit,
                        reference_price=price,
                    )
                )
                created += 1
        await session.commit()
    logger.info("食材种子完成: 新增 %s 条, 更新 %s 条", created, updated)
    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
