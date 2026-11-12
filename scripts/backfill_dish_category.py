#!/usr/bin/env python3
"""回填菜品「互斥大类」并维护 dish_category 字典表 (迁移 0027)

为什么要有这个脚本
    迁移 0027 只建了字典表 + 加了列, recipe.dish_category_code 默认全是 other。
    不回填的话中西筛选形同虚设 —— 所有菜都挤在「其他」里。

规则真源
    判定只写在 app/services/dish_rules.py 的 guess_dish_category(), 与候选加载、
    方案校验共用同一份。脚本不另写一套, 避免"回填的和运行时看到的不一样"。

幂等性
    只改默认值 other 的行, 人工显式归类过的 code 不碰; 加 --force 才整体重算。
    字典表用 INSERT ... 补缺失 code, 不覆盖运维改过的名称/排序/启停。

用法
    python scripts/backfill_dish_category.py --dry-run --preview 30
    python scripts/backfill_dish_category.py
    python scripts/backfill_dish_category.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.database import async_session_factory, close_db  # noqa: E402
from app.models.dish_category import DishCategory as DishCategoryRow  # noqa: E402
from app.models.recipe import Recipe, RecipeIngredient  # noqa: E402
from app.services.dish_rules import DishCategory, guess_dish_category  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-dish-category")

DICTIONARY_SEED = [
    ("chinese", "中餐", "中式家常、川湘粤鲁等地方菜与中式主食", 1),
    ("western", "西餐", "欧美菜式、烘焙、沙拉与西式主食", 2),
    ("japanese_korean", "日韩", "日式与韩式料理", 3),
    ("southeast_asian", "东南亚·南亚", "泰越新马印尼与印度等南亚料理", 4),
    ("other", "其他", "融合菜、饮品甜品与暂未归类的条目", 5),
]


async def sync_dictionary(db) -> None:
    """补齐字典表里的 code; 不覆盖运维手工改过的名称/排序"""
    existing = set((await db.execute(select(DishCategoryRow.code))).scalars().all())
    added = 0
    for code, name, description, order in DICTIONARY_SEED:
        if code in existing:
            continue
        db.add(DishCategoryRow(
            code=code, name=name, description=description, sort_order=order, enabled=True,
        ))
        added += 1
    if added:
        logger.info(f"字典表补入 {added} 个类别 code")
    else:
        logger.info("字典表 5 个类别 code 已齐全")


async def run(force: bool, dry_run: bool, preview: int, limit: int) -> None:
    try:
        async with async_session_factory() as db:
            await sync_dictionary(db)
            stmt = (
                select(Recipe)
                .options(selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient))
                .order_by(Recipe.id)
            )
            if limit:
                stmt = stmt.limit(limit)
            recipes = list((await db.execute(stmt)).scalars().all())
            changes = []
            final = Counter()
            for recipe in recipes:
                current = recipe.dish_category_code or DishCategory.OTHER
                # --force 要能真正按新规则重算, 否则旧值会被当作「人工归类」一直保留
                guessed = guess_dish_category(recipe, ignore_explicit=force)
                if not force and current != DishCategory.OTHER and current != guessed:
                    # 人工显式归类过, 且不是规则默认值 —— 保留
                    final[current] += 1
                    continue
                if guessed != current:
                    changes.append((recipe.id, recipe.name, current, guessed))
                    if not dry_run:
                        recipe.dish_category_code = guessed
                final[guessed] += 1
            logger.info(f"扫描 {len(recipes)} 道菜, 待回填 {len(changes)} 道 (dry-run={dry_run}, force={force})")
            for row in changes[:preview]:
                logger.info(f"  #{row[0]:<4} {row[1][:22]:<24} {row[2]} -> {row[3]} ({DishCategory.LABELS[row[3]]})")
            if len(changes) > preview:
                logger.info(f"  ... 另有 {len(changes) - preview} 道")
            logger.info("回填后分布: " + ", ".join(
                f"{DishCategory.LABELS[code]}={final.get(code, 0)}" for code in DishCategory.ALL
            ))
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
                logger.info(f"已写回 {len(changes)} 道菜的类别")
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="回填菜品互斥大类")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库")
    parser.add_argument("--preview", type=int, default=20, help="预览条数")
    parser.add_argument("--force", action="store_true", help="全量重算, 覆盖人工已填的类别")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 道")
    args = parser.parse_args()
    asyncio.run(run(args.force, args.dry_run, args.preview, args.limit))


if __name__ == "__main__":
    main()
