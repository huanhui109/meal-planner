#!/usr/bin/env python3
"""把 recipe 里「不是一个菜」的条目标成 is_dish=0

为什么会出这场事故
    候选池 396 道里混着 61 条调味品/饮品/甜品/半成品加工 —— 油泼辣子、B52轰炸机、
    速冻水饺。它们的 category 被导入规则强行归成了素菜/小吃/汤羹, 决策引擎里所有
    基于 category 的过滤全部失效, 于是用户点「饭决」屏幕上真的出现过"油泼辣子"。
    迁移 0017 加的 is_dish 列默认 1, 存量数据得靠这一步回填。

做法
    判定只用同一份规则 app/services/dish_rules.guess_is_dish, 本脚本不另写一套 ——
    脚本和服务各写一份必然漂移, 用户断网/联网看到的结果就会不一致。
    命中前先把完整清单导出成 CSV 留给人工复核, 写库永远在导出之后。

只置 0, 不 DELETE
    这些条目在菜谱库里仍然有检索价值(用户搜"糖醋汁"应该搜得到), 它们只是不该出现在
    "今天吃什么"的答案里。删数据是删不回来的。

幂等性
    已经是 0 的不再动, 于是人工改回 1 的那几条不会被下一次跑回来 —— 校正优先。

用法
    python scripts/backfill_recipe_is_dish.py --dry-run
    python scripts/backfill_recipe_is_dish.py                # 正式回填
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.database import async_session_factory, close_db  # noqa: E402
from app.models.recipe import Recipe  # noqa: E402
from app.services.dish_rules import guess_is_dish  # noqa: E402
from sqlalchemy import select  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-is-dish")

CSV_HEADERS = ("id", "name", "source", "cuisine", "category")


def export_csv(path: Path, rows: List[Recipe]) -> None:
    """先落成 CSV 再动数据库 —— 复核清单比回填结果活得久"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(CSV_HEADERS)
        for recipe in rows:
            writer.writerow([
                recipe.id, recipe.name, recipe.source, recipe.cuisine, recipe.category,
            ])


async def run(dry_run: bool, csv_path: Path, preview: int) -> int:
    async with async_session_factory() as session:
        rows = (await session.execute(select(Recipe).order_by(Recipe.id))).scalars().all()
        hits = [r for r in rows if not guess_is_dish(r)]

        export_csv(csv_path, hits)

        todo = [r for r in hits if r.is_dish]
        if not dry_run:
            for recipe in todo:
                recipe.is_dish = False
            await session.commit()

    logger.info("=" * 60)
    logger.info("扫描菜品   = %s 道", len(rows))
    logger.info("判定非菜   = %s 道", len(hits))
    logger.info("本次置 0   = %s 道 (其余已是 0, 人工校正过的不会被拧回来)", len(todo))
    if preview:
        logger.info("-" * 60)
        for recipe in hits[:preview]:
            logger.info("  #%s %s  源分类=%s 品类=%s",
                        recipe.id, recipe.name, recipe.cuisine, recipe.category)
    logger.info("-" * 60)
    logger.info("复核清单   = %s", csv_path.relative_to(ROOT))
    logger.info("模式       = %s", "只看不写 (--dry-run)" if dry_run else "已写回数据库")
    logger.info("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 recipe.is_dish")
    parser.add_argument("--dry-run", action="store_true", help="只看不写")
    parser.add_argument("--preview", type=int, default=15, help="预览条数")
    parser.add_argument("--csv", default="output/non-dish-candidates-2026-09-23.csv",
                        help="复核清单CSV路径(相对项目根)")
    args = parser.parse_args()

    async def _main() -> int:
        # close_db 必须在**同一个**事件循环里 await。写成 asyncio.run(run(...)) 之后再
        # asyncio.run(close_db()) 会在关库时抛 "Event loop is closed", 结果明明写成功了
        # 却打一屏红字, 让人以为失败了。
        try:
            return await run(args.dry_run, ROOT / args.csv, args.preview)
        finally:
            await close_db()

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
