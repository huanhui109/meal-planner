#!/usr/bin/env python3
"""回填菜品「场景层」字段: 烹饪时间 / 适合餐次 / 荤型 / 厨具 / 时令

为什么要有这个脚本
    迁移 0016 只加了列, 存量 396 道菜全是空的。其中 cook_minutes 缺 368 道(93%),
    杀伤力最大: 决策引擎里写的是 `r.cook_minutes or 30`, 等于所有菜都是 30 分钟 ——
    于是「深夜只出快手菜」「超过用户时间上限就换一道」这两条硬规则全成了摆设。
    这是纯数据问题, 不能等凌晨的 LLM 定时任务, 先按规则补上。

做法
    纯规则推断, 不调 LLM: 离线可跑、可重复、结果可预测。
    规则本身放在 app/services/dish_rules.py, 与富集服务共用同一份 —— 两处各写一套
    必然漂移, 脚本补的和服务补的口径不一致, 事后查不清是哪批。
    LLM 之后再精修(recipe_enrich_service), 人工校对过的(manual)两边都不碰。

幂等性
    只填空着的字段, 已填的不动; 加 --force 才整体重算。

用法
    python scripts/backfill_dish_scene_fields.py --dry-run
    python scripts/backfill_dish_scene_fields.py --dry-run --preview 20
    python scripts/backfill_dish_scene_fields.py                # 正式回填
    python scripts/backfill_dish_scene_fields.py --force        # 全量重算
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.database import async_session_factory, close_db  # noqa: E402
from app.models.recipe import EnrichSource, EnrichStatus, Recipe  # noqa: E402
from app.services.dish_rules import (  # noqa: E402
    guess_meal_slots,
    guess_meat_type,
    guess_minutes,
    guess_season,
    guess_tools,
    to_json,
)
from sqlalchemy import select  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-dish-scene")


def collect(recipe: Recipe, force: bool) -> Dict[str, object]:
    """算出一道菜该补什么。只补当前为空的字段"""
    patch: Dict[str, object] = {}

    if force or not recipe.cook_minutes:
        minutes = guess_minutes(recipe)
        if minutes:
            patch["cook_minutes"] = minutes
    if force or not recipe.meat_type:
        meat = guess_meat_type(recipe)
        if meat:
            patch["meat_type"] = meat
    if force or not recipe.meal_slots:
        patch["meal_slots"] = to_json(guess_meal_slots(recipe))
    if force or not recipe.tools:
        patch["tools"] = to_json(guess_tools(recipe))
    if force or not recipe.season:
        patch["season"] = to_json(guess_season(recipe))
    return {k: v for k, v in patch.items() if v is not None}


def is_complete(recipe: Recipe) -> bool:
    """决策所需字段是否齐了。齐了就不再占用定时任务的名额"""
    return bool(
        recipe.cook_minutes and recipe.category and recipe.main_ingredient
        and recipe.meat_type and recipe.meal_slots
        and (recipe.quick_steps or recipe.steps)
    )


async def run(dry_run: bool, limit: int, force: bool, preview: int) -> int:
    async with async_session_factory() as session:
        stmt = select(Recipe).order_by(Recipe.id)
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        total = 0
        patched: Dict[str, int] = {}
        samples: List[str] = []
        for recipe in rows:
            patch = collect(recipe, force)
            if not patch:
                continue
            total += 1
            for key in patch:
                patched[key] = patched.get(key, 0) + 1
            if preview and len(samples) < preview:
                samples.append(
                    f"  {recipe.name}: " + ", ".join(f"{k}={v}" for k, v in patch.items())
                )
            if not dry_run:
                for key, value in patch.items():
                    setattr(recipe, key, value)
                recipe.enriched_at = datetime.now()
                if recipe.enrich_source != EnrichSource.MANUAL:
                    recipe.enrich_source = EnrichSource.RULE
                recipe.enrich_status = (
                    EnrichStatus.DONE if is_complete(recipe) else EnrichStatus.PARTIAL
                )
        if not dry_run:
            await session.commit()

    logger.info("=" * 60)
    logger.info("待补菜品   = %s 道 (共扫描 %s 道)", total, len(rows))
    for key in ("cook_minutes", "meat_type", "meal_slots", "tools", "season"):
        logger.info("  %-14s %s 道", key, patched.get(key, 0))
    if samples:
        logger.info("-" * 60)
        logger.info("预览:")
        for line in samples:
            logger.info(line)
    logger.info("=" * 60)
    logger.info("模式       = %s", "只看不写 (--dry-run)" if dry_run else "已写回数据库")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回填菜品场景层字段")
    parser.add_argument("--dry-run", action="store_true", help="只看不写")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 道")
    parser.add_argument("--force", action="store_true", help="已填的也重算")
    parser.add_argument("--preview", type=int, default=15, help="预览条数")
    args = parser.parse_args()

    async def _main() -> int:
        # close_db 必须在**同一个**事件循环里 await。写成 asyncio.run(run(...)) 之后再
        # asyncio.run(close_db()) 会在关库时抛 "Event loop is closed", 结果明明写成功了
        # 却打一屏红字, 让人以为失败了。
        try:
            return await run(args.dry_run, args.limit, args.force, args.preview)
        finally:
            await close_db()

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
