"""菜谱导入 - SQL 生成单元测试

关注转义安全、幂等语义 (INSERT IGNORE / WHERE NOT EXISTS) 与食材去重。
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from scripts.import_recipes.build_sql import (
    _collect_ingredients,
    render_sql,
    sql_dec,
    sql_int,
    sql_str,
    write_sql,
)
from scripts.import_recipes.normalize import IngredientRecord, RecipeRecord


def _recipe(name: str, ingredients: list[IngredientRecord], **kwargs) -> RecipeRecord:
    return RecipeRecord(name=name, ingredients=ingredients, **kwargs)


def test_sql_str_escapes_quote_backslash_and_null():
    assert sql_str(None) == "NULL"
    assert sql_str("a'b") == "'a''b'"
    assert sql_str("a\\b") == "'a\\\\b'"


def test_sql_number_helpers():
    assert sql_int(None) == "NULL"
    assert sql_int(12.9) == "12"
    assert sql_dec(None) == "NULL"
    assert sql_dec(3) == "CAST(3 AS DECIMAL(10,3))"


def test_collect_ingredients_prefers_first_non_empty_unit():
    salt_empty = _recipe("A", [IngredientRecord("盐", None, "", "适量")])
    salt_grams = _recipe("B", [IngredientRecord("盐", 5.0, "g", "5g")])
    units = _collect_ingredients([salt_empty, salt_grams])
    assert units["盐"] == "g"


def test_render_sql_has_transaction_and_idempotent_guards():
    record = _recipe(
        "番茄炒蛋",
        [IngredientRecord("番茄", 2.0, "个", "2 个")],
        cuisine="素菜",
        difficulty=1,
        cook_minutes=10,
        calories=180,
        protein_g=8.0,
        carb_g=6.0,
        fat_g=9.0,
        steps="1. 炒熟出锅",
        source="howtocook",
    )
    sql = render_sql([record])

    assert "START TRANSACTION;" in sql
    assert sql.rstrip().endswith("COMMIT;")
    # 食材唯一 -> INSERT IGNORE; 菜谱按 name 判重 -> WHERE NOT EXISTS
    assert "INSERT IGNORE INTO ingredient" in sql
    assert "WHERE NOT EXISTS (SELECT 1 FROM recipe WHERE name =" in sql
    assert "INSERT INTO recipe_ingredient" in sql
    assert "菜谱 1 道, 食材 1 种" in sql


def test_render_sql_dedupes_ingredient_across_recipes():
    first = _recipe("A", [IngredientRecord("盐", 1.0, "g", "1g")])
    second = _recipe("B", [IngredientRecord("盐", 2.0, "g", "2g")])
    sql = render_sql([first, second])
    assert sql.count("('盐', 'g',") == 1


def test_render_sql_escapes_recipe_name_in_guard():
    """菜名含单引号时, 判重条件与插入值都要被正确转义, 避免 SQL 注入/语法错误"""
    record = _recipe("老板's 炒饭", [IngredientRecord("米饭", 1.0, "碗", "1 碗")])
    sql = render_sql([record])
    assert "WHERE NOT EXISTS (SELECT 1 FROM recipe WHERE name = '老板''s 炒饭');" in sql


def test_render_sql_skips_ingredient_block_when_recipe_has_none():
    sql = render_sql([_recipe("无食材菜", [])])
    assert "INSERT INTO recipe_ingredient" not in sql


def test_write_sql_returns_size_and_creates_parents():
    record = _recipe("A", [IngredientRecord("盐", 1.0, "g", "1g")])
    base = Path(tempfile.mkdtemp(prefix="recipes_sql_"))
    try:
        output = base / "nested" / "seed.sql"

        size = write_sql([record], output)

        assert output.exists()
        assert size == len(output.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("calories", "500", 500),
        ("calories", "5000", None),  # 越界丢弃
        ("calories", -1, None),
        ("calories", "abc", None),
        ("protein_g", "12.46", 12.5),
        ("protein_g", "999", None),
        ("cook_minutes", "0", None),
        ("cook_minutes", "30", 30),
        ("fat_g", None, None),
    ],
)
def test_backfill_clamp_ranges(key, value, expected):
    from scripts.backfill_recipe_nutrition import _clamp

    assert _clamp(key, value) == expected
