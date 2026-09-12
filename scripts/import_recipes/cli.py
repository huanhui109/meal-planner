"""命令行入口

用法:
  python scripts/import_recipes/cli.py fetch        # 抓取并缓存原始数据
  python scripts/import_recipes/cli.py build-sql    # 生成 data/sql/recipes_seed.sql
  python scripts/import_recipes/cli.py load         # 幂等落库 (走 ORM)
  python scripts/import_recipes/cli.py all          # fetch -> build-sql -> load

通用参数: ``--cache-dir`` / ``--force`` (忽略缓存) / ``--limit N`` (只处理前 N 道, 调试用)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.config import get_settings  # noqa: E402

from scripts.import_recipes import build_sql, normalize, sources  # noqa: E402
from scripts.import_recipes.normalize import RecipeRecord  # noqa: E402

DEFAULT_SQL_OUTPUT = ROOT / "data" / "sql" / "recipes_seed.sql"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("import-recipes")


def resolve_cache_dir(explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else ROOT / path
    configured = get_settings().recipes.cache_dir
    return ROOT / configured


def collect_records(cache_dir: Path, force: bool, limit: Optional[int]) -> List[RecipeRecord]:
    raws = sources.fetch_all(cache_dir, force=force)
    parsed = [normalize.record_from_raw(raw.source, raw.payload) for raw in raws]
    records = [record for record in parsed if record is not None]
    merged = normalize.merge_records(records)
    merged.sort(key=lambda r: r.name)
    if limit:
        merged = merged[:limit]
    logger.info("归一化: 原始 %s 条 -> 合并去重后 %s 道菜谱", len(records), len(merged))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="开源菜谱导入")
    parser.add_argument("command", choices=["fetch", "build-sql", "load", "all"])
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--output", default=str(DEFAULT_SQL_OUTPUT))
    parser.add_argument("--force", action="store_true", help="忽略缓存, 重新联网抓取")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 道 (调试用)")
    args = parser.parse_args()

    cache_dir = resolve_cache_dir(args.cache_dir)

    if args.command == "fetch":
        raws = sources.fetch_all(cache_dir, force=args.force)
        logger.info("抓取完成: %s 条原始记录 (缓存 %s)", len(raws), cache_dir)
        return 0

    records = collect_records(cache_dir, args.force, args.limit)

    if args.command in ("build-sql", "all"):
        size = build_sql.write_sql(records, Path(args.output))
        logger.info("已生成 SQL: %s (%.1f KB)", args.output, size / 1024)

    if args.command in ("load", "all"):
        from scripts.import_recipes import load_db

        result = asyncio.run(load_db.load_records(records))
        logger.info("落库完成: 新增 %(created)s, 跳过 %(skipped)s, 失败 %(failed)s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
