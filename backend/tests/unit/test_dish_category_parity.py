"""菜品类别法典的守门测试

三件事:
  1. shared/dish-category.ts、dish_rules.DishCategory、迁移 0027 的种子行、
     Pydantic 的 Literal 四处 code/label 必须完全一致(静态比对, 不跑 TS 运行时);
  2. guess_dish_category() 的判定口径(含两处实测误判的回归用例);
  3. 类别一致性硬规则: 单一类别通过、跨类别拦截、中西混排给专门文案。
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
from app.schemas.meal import MealContext
from app.services.dish_rules import (
    DishCategory,
    category_conflict,
    category_from_pool_cuisine,
    guess_dish_category,
    normalize_dish_category,
)

ROOT = Path(__file__).resolve().parents[3]
TS_SOURCE = (ROOT / "shared" / "dish-category.ts").read_text(encoding="utf-8")
MIGRATION_SOURCE = (ROOT / "backend" / "alembic" / "versions" / "0027_dish_category.py").read_text(encoding="utf-8")


def _ts_specs():
    block = TS_SOURCE.split("export const DISH_CATEGORIES", 1)[1].split("\n]", 1)[0]
    return re.findall(r"code:\s*'([a-z_]+)',\s*label:\s*'([^']+)'", block)


def _migration_specs():
    spec = importlib.util.spec_from_file_location(
        "migration_0027", ROOT / "backend" / "alembic" / "versions" / "0027_dish_category.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [(row["code"], row["name"]) for row in module.SEED_CATEGORIES]


def test_category_codes_agree_in_all_four_places():
    ts = _ts_specs()
    assert tuple(code for code, _ in ts) == DishCategory.ALL
    assert dict(ts) == DishCategory.LABELS
    assert _migration_specs() == ts
    # Pydantic 的 Literal 参数也要同步, 否则前端传得进来、后端 422
    annotation = MealContext.model_fields["dish_category"].annotation
    literals = set()
    for arg in get_args(annotation):
        literals.update(get_args(arg))
    assert literals == set(DishCategory.ALL)


def test_labels_are_unique_and_codes_are_stable():
    codes = [code for code, _ in _ts_specs()]
    labels = [label for _, label in _ts_specs()]
    assert len(codes) == len(set(codes)) == 5
    assert len(set(labels)) == 5
    assert "中餐" in labels and "西餐" in labels


def test_normalize_never_lets_a_bad_code_escape():
    assert normalize_dish_category(None) == DishCategory.OTHER
    assert normalize_dish_category("") == DishCategory.OTHER
    assert normalize_dish_category("川菜") == DishCategory.OTHER
    assert normalize_dish_category("western") == DishCategory.WESTERN


@pytest.mark.parametrize("name,ingredients,cuisine,expected", [
    ("西红柿炒鸡蛋", ["鸡蛋", "番茄"], None, "chinese"),
    # 实测误判回归: 食材里的「火腿肠」不能把中式炒饭划去西餐
    ("可乐炒饭", ["米饭", "火腿肠", "鸡蛋"], "主食", "chinese"),
    # 「拌饭」太宽泛, 已从日韩词表移除
    ("猪油拌饭", ["米饭", "猪油"], "主食", "chinese"),
    ("红芸豆拌饭", ["姜黄粉", "印度综合香料粉", "大米"], "主食", "southeast_asian"),
    ("日式咖喱饭", ["咖喱", "米饭"], "主食", "japanese_korean"),
    ("韩式拌饭", ["米饭", "泡菜"], "主食", "japanese_korean"),
    ("利提巧卡", ["烤鹰嘴豆粉", "酥油"], "主食", "southeast_asian"),
    ("奶油蘑菇汤", ["奶油", "蘑菇"], "汤羹", "western"),
    ("奶酪培根通心粉", ["通心粉", "培根"], "荤菜", "western"),
    ("冬瓜茶", ["冬瓜"], "饮品", "other"),
])
def test_guess_dish_category(name, ingredients, cuisine, expected):
    recipe = SimpleNamespace(
        name=name, cuisine=cuisine, dish_category_code="other",
        recipe_ingredients=[SimpleNamespace(ingredient=SimpleNamespace(name=n)) for n in ingredients],
    )
    assert guess_dish_category(recipe) == expected


def test_explicit_manual_category_wins_unless_forced():
    recipe = SimpleNamespace(
        name="牛排", cuisine="荤菜", dish_category_code="chinese",
        recipe_ingredients=[],
    )
    assert guess_dish_category(recipe) == "chinese"
    assert guess_dish_category(recipe, ignore_explicit=True) == "western"


def test_pool_cuisine_maps_to_the_same_codes():
    assert category_from_pool_cuisine("家常") == DishCategory.CHINESE
    assert category_from_pool_cuisine("川湘") == DishCategory.CHINESE
    assert category_from_pool_cuisine("西餐") == DishCategory.WESTERN
    assert category_from_pool_cuisine("轻食") == DishCategory.WESTERN
    assert category_from_pool_cuisine("日料") == DishCategory.JAPANESE_KOREAN
    assert category_from_pool_cuisine("东南亚") == DishCategory.SOUTHEAST_ASIAN
    assert category_from_pool_cuisine("没见过的") == DishCategory.OTHER


@pytest.mark.parametrize("codes,expected_fragment", [
    (["chinese", "chinese", "chinese"], None),
    (["western"], None),
    ([], None),
    (["chinese", "western"], "中餐与西餐"),
    (["western", "chinese", "chinese"], "中餐与西餐"),
    (["chinese", "japanese_korean"], "类别必须一致"),
    (["western", "southeast_asian", "other"], "类别必须一致"),
])
def test_category_conflict(codes, expected_fragment):
    error = category_conflict(codes)
    if expected_fragment is None:
        assert error is None
    else:
        assert error and expected_fragment in error


def test_other_is_a_category_not_a_wildcard():
    assert "类别必须一致" in category_conflict(["chinese", "other"])
    assert category_conflict(["other", "other"]) is None
