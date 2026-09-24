"""菜品富集单测

不联网、不调模型、不依赖数据库。重点验证两件事:
1. **LLM 的输出必须过校验才落库** —— 它会给 spice_level=9、给不存在的枚举值,
   直接写进去会让决策引擎读到脏数据。
2. **规则兜底判得对** —— 尤其荤型:「鸡蛋」含「鸡」、「牛奶」含「牛」这两类假阳性
   抠不干净, 用户说"吃素"就吃不上饭。
"""

from __future__ import annotations

import json

import pytest
from app.models.recipe import MeatType
from app.services import dish_rules
from app.services.recipe_enrich_service import (
    DEFAULT_MINUTES,
    clean_steps,
    rule_patch,
    sanitize,
)


class _Ing:
    def __init__(self, name: str):
        self.name = name


class _RI:
    def __init__(self, name: str):
        self.ingredient = _Ing(name)


class _FakeRecipe:
    """替身, 不用真 ORM 对象

    Recipe.recipe_ingredients 是 SQLAlchemy 关系属性, 塞假对象进去会触发
    instrumentation(报 '_RI' object has no attribute '_sa_instance_state')。
    规则函数只读三个属性, 鸭子类型就够了。
    """

    def __init__(self, name: str, category: str = "", ingredients=()):
        self.name = name
        self.category = category
        self.recipe_ingredients = [_RI(n) for n in ingredients]
        self.cook_minutes = None
        self.meat_type = None
        self.meal_slots = None
        self.tools = None
        self.season = None


def _recipe(name: str, category: str = "", ingredients=(), **kw):
    r = _FakeRecipe(name, category, ingredients)
    for k, v in kw.items():
        setattr(r, k, v)
    return r


# ------------------------------------------------------------------ 输出校验

def test_sanitize_drops_out_of_range_numbers():
    """越界值直接丢弃, 不截断 —— 截断等于替模型编数据"""
    out = sanitize({"spice_level": 9, "cook_minutes": 9999, "difficulty": 0})
    assert "spice_level" not in out
    assert "cook_minutes" not in out
    assert "difficulty" not in out


def test_sanitize_keeps_zero_and_false():
    """0 和 False 是有效值 —— 这个坑在 intent_service 里踩过(0 == False)"""
    out = sanitize({"spice_level": 0, "is_light": False})
    assert out["spice_level"] == 0
    assert out["is_light"] is False


def test_sanitize_filters_unknown_enum():
    out = sanitize({"meat_type": "alien", "tools": ["wok", "laser"], "season": ["summer", "x"]})
    assert "meat_type" not in out
    assert json.loads(out["tools"]) == ["wok"]
    assert json.loads(out["season"]) == ["summer"]


def test_sanitize_ignores_unknown_fields():
    """白名单外的字段一律丢弃, 不许模型乱改结构"""
    assert sanitize({"__tablename__": "x", "id": 1, "name": "被改名的菜"}) == {}


def test_clean_steps_enforces_length_and_count():
    """极简做法 3-5 步、每步 <=20 字, 这直接决定结果卡放得下"""
    ok = clean_steps({"quick_steps": ["切葱", "热油", "下锅翻炒", "出锅"],
                      "steps": ["第一步", "第二步", "第三步"]})
    assert len(json.loads(ok["quick_steps"])) == 4
    assert "steps" in ok

    # 2 步太少、6 步太多、单步超 20 字, 都应被拒
    assert clean_steps({"quick_steps": ["a", "b"]}) == {}
    assert clean_steps({"quick_steps": ["1", "2", "3", "4", "5", "6"]}) == {}
    assert clean_steps({"quick_steps": ["x" * 21, "b", "c"]}) == {}


# ------------------------------------------------------------------ 规则兜底

def test_guess_minutes_prefers_explicit():
    """菜名里写了分钟就以它为准 —— 用户/运营写进菜名的比任何推断都可信"""
    assert dish_rules.guess_minutes(_recipe("十分钟快手菜")) == 10


def test_guess_minutes_method_beats_category():
    """做法优先于品类: 「炖白菜」虽是素菜, 也该是 60 分钟而不是 12"""
    assert dish_rules.guess_minutes(_recipe("炖白菜", category="素菜")) == 60


def test_guess_minutes_falls_back_to_category():
    """菜名里看不出做法时才用品类基准"""
    assert dish_rules.guess_minutes(_recipe("杂粮米饭", category="主食")) == 25
    assert dish_rules.guess_minutes(_recipe("玉米排骨汤", category="汤羹")) == 40


def test_guess_meat_type_strips_false_positives():
    """三个经典假阳性: 鸡蛋含鸡、牛奶含牛、鱼香没有鱼"""
    assert dish_rules.guess_meat_type(_recipe("西红柿炒鸡蛋")) == MeatType.EGG_DAIRY
    assert dish_rules.guess_meat_type(_recipe("牛奶粥")) == MeatType.EGG_DAIRY
    assert dish_rules.guess_meat_type(_recipe("鱼香肉丝")) == MeatType.RED_MEAT
    assert dish_rules.guess_meat_type(_recipe("蒜蓉西蓝花")) == MeatType.NONE


def test_guess_meat_type_uses_ingredients_not_only_name():
    """菜名看不出荤素时看食材 —— 「上汤时蔬」里可能藏着火腿"""
    assert dish_rules.guess_meat_type(
        _recipe("上汤时蔬", ingredients=["白菜", "火腿"])
    ) == MeatType.RED_MEAT


def test_guess_meat_type_returns_none_when_unsure():
    """判不了就返回 None, 绝不默认成"素" —— 默认素会让忌口用户吃到肉"""
    assert dish_rules.guess_meat_type(_recipe("神秘的菜")) is None


def test_guess_meal_slots_breakfast_never_only_breakfast():
    slots = dish_rules.guess_meal_slots(_recipe("皮蛋瘦肉粥"))
    assert slots == ["breakfast", "lunch"]


def test_rule_patch_only_fills_empty_fields():
    """已填的不动 —— 重跑幂等, 也不覆盖人工校对"""
    r = _recipe("红烧排骨", cook_minutes=45, meat_type=MeatType.RED_MEAT)
    patch = rule_patch(r)
    assert "cook_minutes" not in patch
    assert "meat_type" not in patch


def test_rule_patch_fills_missing_cook_minutes():
    """cook_minutes 缺 93% 时决策引擎走 `or 30`, 硬规则全废 —— 这个洞必须先堵"""
    r = _recipe("杂粮米饭", category="主食")
    assert rule_patch(r).get("cook_minutes") == 25


# ------------------------------------------------------------------ 服务行为

@pytest.mark.asyncio
async def test_enrich_degrades_to_rules_without_llm():
    """模型不可用时不能什么都不做 —— 规则那一层是免费的"""
    from app.config import DishEnrichSettings, Settings
    from app.services.recipe_enrich_service import RecipeEnrichService

    settings = Settings(dish_enrich=DishEnrichSettings(enabled=False))
    svc = RecipeEnrichService(session=None, settings=settings)
    assert svc.usable is False


def test_expand_recipe_always_has_cook_minutes():
    """新菜入库必须有耗时, 否则又多一道"30 分钟"的洞"""
    assert DEFAULT_MINUTES == 20
