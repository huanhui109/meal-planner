"""SQL 生成 - 把归一化后的菜谱渲染成可直接执行的插入脚本

设计要点:
  * 外键安全: 先 ingredient (按 name 唯一) -> 再 recipe -> 最后 recipe_ingredient。
  * 幂等: ingredient 用 ``INSERT IGNORE``; recipe 因 name 无唯一约束, 用
    ``WHERE NOT EXISTS``; recipe_ingredient 以"该菜谱是否已有用量"为闸门。
  * 因此脚本可以重复执行而不产生重复行。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List

from .normalize import RecipeRecord

INGREDIENT_CHUNK = 200


def sql_str(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def sql_dec(value: object) -> str:
    if value is None:
        return "NULL"
    return f"CAST({float(value):g} AS DECIMAL(10,3))"


def sql_int(value: object) -> str:
    if value is None:
        return "NULL"
    return str(int(value))


def _collect_ingredients(records: List[RecipeRecord]) -> Dict[str, str]:
    """食材名 -> 标准单位 (取首个非空单位)"""
    units: Dict[str, str] = {}
    for record in records:
        for item in record.ingredients:
            if item.name not in units or (not units[item.name] and item.unit):
                units[item.name] = item.unit or ""
    return units


def _render_ingredient_insert(units: Dict[str, str]) -> List[str]:
    lines: List[str] = []
    items = sorted(units.items())
    for start in range(0, len(items), INGREDIENT_CHUNK):
        chunk = items[start : start + INGREDIENT_CHUNK]
        values = ",\n".join(
            f"({sql_str(name)}, {sql_str(unit or None)}, NOW(), NOW())" for name, unit in chunk
        )
        lines.append(
            "INSERT IGNORE INTO ingredient (name, standard_unit, created_at, updated_at) VALUES\n"
            + values
            + ";"
        )
    return lines


def _render_recipe_insert(record: RecipeRecord) -> str:
    columns = (
        "name, cuisine, difficulty, cook_minutes, calories, protein_g, carb_g, fat_g, "
        "steps, source, created_at, updated_at"
    )
    values = ", ".join(
        [
            sql_str(record.name),
            sql_str(record.cuisine),
            sql_int(record.difficulty),
            sql_int(record.cook_minutes),
            sql_int(record.calories),
            sql_dec(record.protein_g),
            sql_dec(record.carb_g),
            sql_dec(record.fat_g),
            sql_str(record.steps or None),
            sql_str(record.source),
            "NOW()",
            "NOW()",
        ]
    )
    return (
        f"INSERT INTO recipe ({columns})\n"
        f"SELECT {values} FROM DUAL\n"
        f"WHERE NOT EXISTS (SELECT 1 FROM recipe WHERE name = {sql_str(record.name)});"
    )


def _render_recipe_ingredient_insert(record: RecipeRecord) -> List[str]:
    if not record.ingredients:
        return []
    rows = []
    for item in record.ingredients:
        rows.append(
            "    SELECT "
            f"{sql_str(item.name)} AS iname, "
            f"{sql_dec(item.quantity)} AS quantity, "
            f"{sql_str(item.unit or '')} AS unit, "
            f"{sql_str(item.amount_text or None)} AS amount_text"
        )
    derived = "\n    UNION ALL\n".join(rows)
    return [
        "INSERT INTO recipe_ingredient "
        "(recipe_id, ingredient_id, quantity, unit, amount_text, created_at, updated_at)\n"
        "SELECT r.id, i.id, v.quantity, v.unit, v.amount_text, NOW(), NOW()\n"
        "FROM recipe r\n"
        "JOIN (\n" + derived + "\n) AS v\n"
        "JOIN ingredient i ON i.name = v.iname\n"
        f"WHERE r.name = {sql_str(record.name)}\n"
        "  AND NOT EXISTS (SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id = r.id);"
    ]


def render_sql(records: List[RecipeRecord]) -> str:
    units = _collect_ingredients(records)
    now = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    header = [
        "-- 开源菜谱种子数据 (自动生成, 请勿手改)",
        "-- 来源: proj.kitchen (MIT) + HowToCook (Unlicense), 由 scripts/import_recipes 合并去重",
        f"-- 生成时间: {now}",
        f"-- 菜谱 {len(records)} 道, 食材 {len(units)} 种",
        "-- 说明: 脚本幂等, 可重复执行; 营养缺失字段由 scripts/backfill_recipe_nutrition.py 回填",
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        "",
    ]

    body: List[str] = []
    body.append("-- 1. 食材 (按 name 唯一, 已存在则跳过)")
    body.extend(_render_ingredient_insert(units))
    body.append("")
    body.append("-- 2. 菜谱 (name 无唯一约束, 用 NOT EXISTS 保证幂等)")
    for record in sorted(records, key=lambda r: r.name):
        body.append(_render_recipe_insert(record))
    body.append("")
    body.append("-- 3. 菜谱-食材用量 (以'该菜谱尚无用量'为闸门)")
    for record in sorted(records, key=lambda r: r.name):
        body.extend(_render_recipe_ingredient_insert(record))
    body.append("")
    body.append("COMMIT;")
    body.append("")
    return "\n".join(header + body)


def write_sql(records: List[RecipeRecord], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    content = render_sql(records)
    output.write_text(content, encoding="utf-8")
    return len(content)
