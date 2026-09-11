#!/usr/bin/env python3
"""菜谱营养批量补全 - 用 LLM 降级链回填缺失的热量与三大营养素

导入的开源菜谱大多只有菜名/食材/步骤, 缺 ``calories`` / ``protein_g`` / ``carb_g`` /
``fat_g`` (HowToCook 有时给卡路里)。本地优先菜单编排要求热量非空才可入选, 所以这里
复用现有 LLM 降级链分批补全。

只填 NULL 字段, 已存在的值不覆盖; 因此可以随时中断重跑。
用法: python scripts/backfill_recipe_nutrition.py [--batch-size 20] [--limit 100]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.config import get_settings  # noqa: E402
from app.database import async_session_factory, close_db  # noqa: E402
from app.llm.fallback_chain import build_fallback_chain  # noqa: E402
from app.models.recipe import Recipe  # noqa: E402
from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-nutrition")

FIELDS = ("calories", "protein_g", "carb_g", "fat_g", "cook_minutes")
SYSTEM_PROMPT = (
    "你是家庭膳食营养数据库。给定菜名与主要食材, 估算【一人份】的热量、三大营养素与烹饪时间。\n"
    '只输出 JSON 对象: {"items":[{"name":"","calories":0,"protein_g":0.0,"carb_g":0.0,'
    '"fat_g":0.0,"cook_minutes":0}]}\n'
    "规则: calories 为整数 kcal; protein_g/carb_g/fat_g 为克(g), 保留 1 位小数; "
    "cook_minutes 为整数分钟; name 必须与输入菜名完全一致; 不要输出任何解释。"
)

# 合理区间, 越界值直接丢弃 (LLM 偶尔会给出 5000 kcal 这种离谱值)
LIMITS = {
    "calories": (0, 2000),
    "protein_g": (0.0, 300.0),
    "carb_g": (0.0, 400.0),
    "fat_g": (0.0, 300.0),
    "cook_minutes": (1, 300),
}


def _pending_filter():
    return or_(
        Recipe.calories.is_(None),
        Recipe.protein_g.is_(None),
        Recipe.carb_g.is_(None),
        Recipe.fat_g.is_(None),
        Recipe.cook_minutes.is_(None),
    )


def _describe(recipe: Recipe) -> str:
    names = [
        row.ingredient.name
        for row in (recipe.recipe_ingredients or [])
        if row.ingredient is not None and row.ingredient.name
    ]
    ingredient_text = "、".join(names[:15]) or "未知"
    return f"- {recipe.name} | 食材: {ingredient_text}"


def _build_messages(recipes: List[Recipe]) -> List[Dict[str, str]]:
    body = "\n".join(_describe(recipe) for recipe in recipes)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"请为下列 {len(recipes)} 道菜估算营养:\n{body}"},
    ]


def _clamp(key: str, value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    low, high = LIMITS[key]
    if number < low or number > high:
        return None
    return int(number) if key in ("calories", "cook_minutes") else round(number, 1)


def _apply(recipe: Recipe, item: dict) -> int:
    changed = 0
    for key in FIELDS:
        if getattr(recipe, key) is not None:
            continue
        value = _clamp(key, item.get(key))
        if value is not None:
            setattr(recipe, key, value)
            changed += 1
    return changed


async def backfill(batch_size: int, limit: Optional[int]) -> dict:
    settings = get_settings()
    if settings.llm.demo:
        logger.warning("当前为 demo 模式 (APP__LLM__DEMO=true), 不调用真实模型, 已跳过")
        return {"skipped": True, "recipes": 0}

    llm = build_fallback_chain(settings)
    attempts = max(1, settings.recipes.nutrition_max_attempts)
    processed = updated = 0
    batches = 0

    while True:
        if limit is not None and processed >= limit:
            break
        size = batch_size if limit is None else min(batch_size, limit - processed)
        async with async_session_factory() as session:
            stmt = (
                select(Recipe)
                .options(selectinload(Recipe.recipe_ingredients))
                .where(_pending_filter())
                .order_by(Recipe.id)
                .limit(size)
            )
            recipes = list((await session.execute(stmt)).scalars().all())
            if not recipes:
                break

            payload: Optional[dict] = None
            messages = _build_messages(recipes)
            for attempt in range(1, attempts + 1):
                try:
                    payload = await llm.chat_with_json(
                        messages=messages, temperature=0.2, max_tokens=settings.llm.primary.max_tokens
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - LLM/解析失败都要能重试
                    logger.warning("批次 %s 第 %s 次调用失败: %s", batches + 1, attempt, exc)
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                logger.warning("批次 %s 未返回可用结果, 跳过这几道菜", batches + 1)
                processed += len(recipes)
                batches += 1
                continue

            items = {str(item.get("name", "")).strip(): item for item in payload["items"] if isinstance(item, dict)}
            for recipe in recipes:
                item = items.get(recipe.name)
                if item and _apply(recipe, item) > 0:
                    updated += 1
            await session.commit()
            processed += len(recipes)
            batches += 1
            logger.info("批次 %s: 处理 %s 道, 累计补全 %s 道", batches, processed, updated)

    await close_db()
    return {"skipped": False, "recipes": updated, "batches": batches}


def main() -> int:
    parser = argparse.ArgumentParser(description="菜谱营养批量补全")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少道 (调试用)")
    args = parser.parse_args()

    batch_size = args.batch_size or get_settings().recipes.nutrition_batch_size
    result = asyncio.run(backfill(max(1, batch_size), args.limit))
    if not result.get("skipped"):
        logger.info("营养补全完成: 补全 %s 道, 共 %s 批", result["recipes"], result["batches"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
