"""菜谱导入 - 归一化单元测试

覆盖两个异构数据源的字段映射、用量解析、脏名称清洗与按菜名合并去重。
"""
from __future__ import annotations

import pytest

from scripts.import_recipes.normalize import (
    IngredientRecord,
    RecipeRecord,
    _finalize_name,
    clean_dish_name,
    clean_proj_ingredient,
    map_difficulty,
    merge_records,
    parse_ingredient_line,
    record_from_raw,
)


def test_clean_dish_name_strips_spaces_and_suffix():
    assert clean_dish_name("  番茄炒蛋 的做法 ") == "番茄炒蛋"
    assert clean_dish_name("宫保鸡丁") == "宫保鸡丁"
    assert clean_dish_name("") == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("★★★", 3),
        ("★", 1),
        ("★★★★★★", 5),  # 超过 5 星收敛到 5
        (7, 5),
        (0, 1),
        ("简单", 1),
        ("中等", 3),
        ("困难", 5),
        ("3", 3),
        ("", None),
        (None, None),
    ],
)
def test_map_difficulty(value, expected):
    assert map_difficulty(value) == expected


@pytest.mark.parametrize(
    ("line", "name", "quantity", "unit"),
    [
        ("* 黄瓜 200 克", "黄瓜", 200.0, "g"),
        ("* 西红柿 1 个", "西红柿", 1.0, "个"),
        ("- 100 ml 水", "水", 100.0, "ml"),
        ("* 10g 吉利丁", "吉利丁", 10.0, "g"),
        ("- 1 枚咸鸭蛋", "咸鸭蛋", 1.0, "个"),
        ("* 2 个鸡蛋", "鸡蛋", 2.0, "个"),
        ("- 八角 两个", "八角", None, ""),
        ("* `油`", "油", None, ""),
        ("* 白糖 or 冰糖", "白糖", None, ""),
    ],
)
def test_parse_ingredient_line_formats(line, name, quantity, unit):
    record = parse_ingredient_line(line)
    assert record is not None
    assert record.name == name
    assert record.quantity == quantity
    assert record.unit == unit


@pytest.mark.parametrize(
    "line",
    [
        "* 3 个 = 份数 * 2",  # 换算说明
        "* 叶菜类蔬菜：300g",  # 冒号说明行
        "* 1 汤匙 = 15ml",  # 换算表
        "* 调一个灵魂料汁儿",  # 动词开头的句子
        "* 一般一个人一顿可以食用",  # 纯说明
        "* 干净密封玻璃或陶瓷容器",  # 厨具/容器
        "* 不粘锅",  # 厨具
    ],
)
def test_parse_ingredient_line_rejects_prose_and_tools(line):
    assert parse_ingredient_line(line) is None


@pytest.mark.parametrize(
    ("raw_name", "raw_amount", "expected_name"),
    [
        ("肋排 =", "750g", "肋排"),
        ("土豆 =", "适量", "土豆"),
        ("叶菜类蔬菜：300g", "~ 500g", "叶菜类蔬菜"),
        ("里脊肉 200g", "适量", "里脊肉"),
        ("干辣椒（依照个人口味）2-3 个，切碎", "适量", "干辣椒"),
        ("味精，看个人口味，不要放多，5g 即可。", "适量", "味精"),
        ("食用油（炸丸子用）500ml", "适量", "食用油"),
        ("瓠瓜（葫芦）1 根（约", "400g）", "瓠瓜"),
        ("1 个鸡蛋（正常中等大小，约", "60g）", "鸡蛋"),
        ("100°C 沸水", "1500ml", "沸水"),
        ("30°C 温水", "1500ml", "温水"),
        ("甘露咖啡酒", "10ml", "甘露咖啡酒"),
    ],
)
def test_clean_proj_ingredient_extracts_core_name(raw_name, raw_amount, expected_name):
    record = clean_proj_ingredient(raw_name, raw_amount)
    assert record is not None
    assert record.name == expected_name


@pytest.mark.parametrize("raw_name", ["1 汤匙 =", "1 :", ""])
def test_clean_proj_ingredient_drops_junk(raw_name):
    assert clean_proj_ingredient(raw_name, "适量") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("`油`", "油"),
        ("白糖 or 冰糖", "白糖"),
        ("全脂牛奶/奶油", "全脂牛奶"),
        ("菜籽油两斤", "菜籽油"),
        ("白糖 半汤匙", "白糖"),
        ("青花椒 一小把", "青花椒"),
        ("洋葱 半个", "洋葱"),
        ("Masala 粉一包", "Masala 粉"),
        ("温水 约", "温水"),
    ],
)
def test_finalize_name(raw, expected):
    assert _finalize_name(raw) == expected


def _rec(name: str, **kwargs) -> RecipeRecord:
    return RecipeRecord(name=name, **kwargs)


def test_merge_records_fills_gaps_without_overwriting():
    proj = RecipeRecord(
        name="番茄炒蛋",
        cuisine="素菜",
        difficulty=1,
        ingredients=[IngredientRecord("番茄", 2.0, "个", "2 个")],
        source="proj_kitchen",
        sources={"proj_kitchen"},
    )
    how = RecipeRecord(
        name="番茄炒蛋",
        calories=180,
        cook_minutes=15,
        steps="1. 炒熟出锅",
        ingredients=[IngredientRecord("鸡蛋", 3.0, "个", "3 个")],
        source="howtocook",
        sources={"howtocook"},
    )

    merged = merge_records([proj, how])

    assert len(merged) == 1
    only = merged[0]
    # 目标已有字段不被覆盖
    assert only.cuisine == "素菜"
    assert only.difficulty == 1
    assert [item.name for item in only.ingredients] == ["番茄"]
    # 缺口由另一源补齐
    assert only.calories == 180
    assert only.cook_minutes == 15
    assert only.steps == "1. 炒熟出锅"
    # 来源合并, 且 proj.kitchen 优先
    assert only.sources == {"proj_kitchen", "howtocook"}
    assert only.source == "proj_kitchen"


def test_merge_records_keeps_first_value_on_conflict():
    first = _rec("红烧肉", calories=100, sources={"proj_kitchen"})
    second = _rec("红烧肉", calories=999, sources={"howtocook"})
    assert merge_records([first, second])[0].calories == 100


def test_merge_records_dedupes_by_name():
    records = [_rec("A", sources={"howtocook"}), _rec("A", sources={"howtocook"}), _rec("B", sources={"howtocook"})]
    assert len(merge_records(records)) == 2


def test_record_from_raw_howtocook_markdown():
    markdown = (
        "# 番茄炒蛋\n\n"
        "## 计算\n\n* 番茄 2 个\n* 鸡蛋 3 个\n\n"
        "## 操作\n\n1. 炒熟出锅\n"
    )
    record = record_from_raw("howtocook", {"category": "vegetable_dish", "text": markdown})
    assert record is not None
    assert record.name == "番茄炒蛋"
    assert record.cuisine == "素菜"
    assert {item.name for item in record.ingredients} == {"番茄", "鸡蛋"}
    assert record.steps.startswith("1. ")


def test_record_from_raw_rejects_unknown_source():
    assert record_from_raw("bogus", {"text": "# x"}) is None
    assert record_from_raw("proj_kitchen", "not-a-dict") is None
