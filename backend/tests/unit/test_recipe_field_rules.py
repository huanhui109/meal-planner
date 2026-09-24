"""回填脚本的纯规则单测 —— 规则一改这里就会红, 防止「回填出垃圾数据」"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# tests/unit -> tests -> backend -> 项目根
_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backfill_recipe_decision_fields.py"
_spec = importlib.util.spec_from_file_location("backfill_decide_fields", _SCRIPT)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)


# --------------------------------------------------------------------------- 品类

@pytest.mark.parametrize(
    "name, ingredients, expected",
    [
        ("红烧肉", ["五花肉", "生抽", "冰糖"], "荤菜"),
        ("清蒸鲈鱼", ["鲈鱼", "姜", "蒸鱼豉油"], "荤菜"),
        ("西红柿炒鸡蛋", ["西红柿", "鸡蛋", "盐"], "荤菜"),
        ("青椒土豆丝", ["土豆", "青椒", "干辣椒"], "素菜"),
        # 配料级的肉末不该让素菜变荤
        ("麻婆豆腐", ["嫩豆腐", "牛肉末", "豆瓣酱", "花椒粉"], "素菜"),
        ("干煸豆角", ["四季豆", "肉末", "干辣椒"], "素菜"),
        ("蛋炒饭", ["米饭", "鸡蛋", "小葱"], "主食"),
        ("皮蛋瘦肉粥", ["大米", "皮蛋", "瘦肉"], "主食"),
        ("番茄鸡蛋面", ["面条", "西红柿", "鸡蛋"], "面食"),
        ("葱油拌面", ["面条", "小葱", "生抽"], "面食"),
        ("番茄蛋汤", ["西红柿", "鸡蛋", "水"], "汤羹"),
        ("凉拌黄瓜", ["黄瓜", "蒜", "香醋"], "凉菜"),
    ],
)
def test_category(name, ingredients, expected):
    assert rules.infer_category(name, ingredients) == expected


def test_category_falls_back_to_veg_without_any_hint():
    assert rules.infer_category("炒时蔬", ["青菜", "大蒜", "盐"]) == "素菜"


# --------------------------------------------------------------------------- 主料

@pytest.mark.parametrize(
    "name, ingredients, category, expected",
    [
        ("麻婆豆腐", ["嫩豆腐", "牛肉末", "豆瓣酱", "花椒粉"], "素菜", "豆腐"),
        ("干煸豆角", ["四季豆", "肉末", "干辣椒"], "素菜", "四季豆"),
        ("香菇滑鸡", ["鸡胸肉", "香菇", "姜", "淀粉"], "荤菜", "鸡胸肉"),
        ("番茄鸡蛋面", ["面条", "西红柿", "鸡蛋"], "面食", "面条"),
        ("牛奶粥", ["牛奶", "大米"], "主食", "米饭"),
        ("清蒸鲈鱼", ["鲈鱼", "姜", "小葱"], "荤菜", "鲈鱼"),
        ("红烧肉", ["五花肉", "生抽", "冰糖"], "荤菜", "五花肉"),
        # 主料归一化: 不同部位的牛肉算同一条主料, 「连续两餐不重样」才真的生效
        ("番茄牛腩", ["牛腩", "番茄", "洋葱"], "荤菜", "牛肉"),
        ("水煮牛肉", ["牛里脊", "豆芽", "豆瓣酱"], "荤菜", "牛肉"),
    ],
)
def test_main_ingredient(name, ingredients, category, expected):
    assert rules.infer_main_ingredient(name, ingredients, category) == expected


def test_seasoning_never_becomes_main_ingredient():
    # 鸡精含「鸡」、蚝油含「蚝」, 不过滤的话会被当成荤菜主料
    assert rules.is_seasoning("鸡精") is True
    assert rules.is_seasoning("蚝油") is True
    assert rules.is_seasoning("干辣椒") is True
    assert rules.is_seasoning("五花肉") is False
    assert rules.infer_main_ingredient("炒时蔬", ["鸡精", "蚝油", "青菜"], "素菜") == "青菜"


def test_main_ingredient_falls_back_to_name_without_ingredients():
    assert rules.infer_main_ingredient("红烧排骨", [], "荤菜") == "排骨"


# --------------------------------------------------------------------------- 辣度 / 味型 / 轻食

def test_spice_level_scales_with_chili_sources():
    assert rules.infer_spice_level("水煮牛肉", ["牛里脊", "豆瓣酱", "干辣椒", "花椒"]) >= 3
    assert rules.infer_spice_level("清蒸鲈鱼", ["鲈鱼", "姜", "蒸鱼豉油"]) == 0
    assert 0 <= rules.infer_spice_level("宫保鸡丁", ["鸡胸肉", "干辣椒"]) <= 4


def test_flavor_tags_use_fixed_vocabulary_and_never_empty():
    flavors = rules.infer_flavor_tags(["鲈鱼", "姜", "蒸鱼豉油"], 0)
    assert flavors and set(flavors) <= set(rules.FLAVOR_VOCAB)
    assert "辣" in rules.infer_flavor_tags(["牛肉", "干辣椒"], 3)


def test_is_light_rejects_heavy_dishes():
    assert rules.infer_is_light("红烧肉", "荤菜", 520, 90, 0) is False
    assert rules.infer_is_light("辣子鸡", "荤菜", 500, 40, 4) is False
    assert rules.infer_is_light("蒜蓉炒时蔬", "素菜", 120, 8, 0) is True


# --------------------------------------------------------------------------- 极简做法

def test_quick_steps_split_and_clipped():
    steps = "鸡蛋打散炒至凝固盛出, 西红柿炒出汁后混合, 加盐调味。"
    out = rules.build_quick_steps(steps)
    assert out == ["鸡蛋打散炒至凝固盛出", "西红柿炒出汁后混合", "加盐调味"]
    assert all(len(s) <= rules.MAX_STEP_LEN for s in out)


def test_quick_steps_truncates_overlong_step():
    long_step = "把土豆切成非常细的丝然后放进清水里浸泡十分钟去掉多余的淀粉再捞出来沥干水分"
    out = rules.build_quick_steps(long_step)
    assert len(out) == 1
    assert len(out[0]) <= rules.MAX_STEP_LEN


def test_quick_steps_empty_when_no_steps():
    assert rules.build_quick_steps(None) == []
    assert rules.build_quick_steps("  ") == []


# --------------------------------------------------------------------------- 整体

def test_infer_all_produces_consistent_payload():
    result = rules.infer_all(
        name="水煮牛肉",
        ingredients=["牛里脊", "豆芽", "豆瓣酱", "干辣椒", "花椒"],
        steps_text="牛肉切片抓匀, 豆芽焯熟垫底, 炒香豆瓣酱加汤烧开, 牛肉烫至变色, 连汤倒碗淋热油。",
        minutes=35,
        calories=480,
    )
    assert result["category"] == "荤菜"
    assert result["main_ingredient"] == "牛肉"
    assert result["spice_level"] >= 3
    assert result["is_light"] is False

    tags = json.loads(result["tags"])
    assert tags and set(tags) <= set(rules.TAG_VOCAB)
    assert "热辣" in tags

    flavors = json.loads(result["flavor_tags"])
    assert flavors and set(flavors) <= set(rules.FLAVOR_VOCAB)

    quick = json.loads(result["quick_steps"])
    assert 3 <= len(quick) <= rules.MAX_QUICK_STEPS
    assert all(len(s) <= rules.MAX_STEP_LEN for s in quick)

    assert len(result["cover_text"]) <= 20


def test_infer_all_is_deterministic():
    args = ("红烧肉", ["五花肉", "生抽", "冰糖", "八角"], None, 90, 520)
    assert rules.infer_all(*args) == rules.infer_all(*args)


def test_drink_detection_ignores_dishes_cooked_with_beer():
    assert rules.looks_like_drink("Mojito莫吉托") is True
    assert rules.looks_like_drink("冬瓜茶") is True
    assert rules.looks_like_drink("乡村啤酒鸭") is False
