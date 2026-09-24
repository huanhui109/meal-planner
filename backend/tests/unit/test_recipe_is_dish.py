"""is_dish 判定单测 —— 2026-09-23 事故的回归防线

为什么这里盯得这么死:
    这次事故不是推错了排序, 是把「油泼辣子」「B52轰炸机」真的推给了用户。
    反方向的错杀伤力更大却没人会发现 —— 一道正常的菜被判成非菜, 结果是用户永远
    吃不到它, 日志里还留不下痕迹。所以两头都要管: 清单里的必须判 False,
    正常菜必须判 True。
"""
from __future__ import annotations

import ast
import csv
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services.decision_service import DecisionService
from app.services.dish_rules import (
    NON_DISH_NAMES,
    NON_DISH_SOURCE_CATEGORIES,
    dish_only,
    guess_is_dish,
    is_dish_flag,
)
from app.services.fridge_menu_service import FridgeMenuService
from app.services.generation_service import MenuGenerationPipeline
from app.services.replacement_service import ReplacementService

ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = ROOT / "output" / "non-dish-candidates-2026-09-23.csv"


def recipe(name: str, cuisine: str | None = None) -> SimpleNamespace:
    """规则函数只吃 name 和 cuisine, 拿朴素对象当桩够了"""
    return SimpleNamespace(name=name, cuisine=cuisine)


# --------------------------------------------------------------------------- 非菜必须剔除


@pytest.mark.parametrize("name", sorted(NON_DISH_NAMES))
def test_every_listed_entry_is_not_a_dish(name):
    assert guess_is_dish(recipe(name, None)) is False


@pytest.mark.parametrize("name", sorted(NON_DISH_NAMES))
def test_listed_entry_stays_out_whatever_its_cuisine_says(name):
    """cuisine 列将来会被清成真菜系 —— 换来换去都不许把它们放回来"""
    for cuisine in (None, "", "川菜", "家常菜"):
        assert guess_is_dish(recipe(name, cuisine)) is False


def test_manifest_size_matches_the_reviewed_scope():
    assert len(NON_DISH_NAMES) == 54


def test_half_finished_source_categories_are_not_blacklisted():
    """「半成品加工」描述加工程度, 不是"是不是一道菜"

    速冻水饺/炸薯条/空气炸锅鸡翅中确实是一顿饭。把它们按源分类整档拦掉会让夜宵
    轻食池进一步缩水 —— 真正该拦的是蹭进这一档的调味品和甜品, 它们由下面的
    原名表与后缀表精确命中。
    """
    assert "半成品加工" not in NON_DISH_SOURCE_CATEGORIES
    assert "半成品" not in NON_DISH_SOURCE_CATEGORIES
    assert guess_is_dish(recipe("空气炸锅鸡翅中", "半成品加工")) is True
    assert guess_is_dish(recipe("懒人蛋挞", "半成品加工")) is False
    assert guess_is_dish(recipe("牛油火锅底料", "半成品加工")) is False


@pytest.mark.skipif(not CSV_PATH.exists(), reason="回填脚本还没跑过, 没有复核清单")
def test_manifest_csv_has_not_drifted_from_the_rule():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert {row["name"] for row in rows} == NON_DISH_NAMES
    # 「半成品加工」整档不该被拦, 且现有分类本身不可信(番茄红酱被填成"荤菜"),
    # 所以这三个靠原名表精确命中。钉住例外名单: 将来有人加第四条, 这里会红,
    # 逼他先确认是不是误伤, 而不是默默把整个分类捞回来。
    out_of_category = {row["name"] for row in rows
                       if row["cuisine"] not in NON_DISH_SOURCE_CATEGORIES}
    assert out_of_category == {"懒人蛋挞", "牛油火锅底料", "番茄红酱"}


# --------------------------------------------------------------------------- 正常菜必须留下


@pytest.mark.parametrize(
    "name, cuisine",
    [
        # C 档拧回回来的: 半成品/速冻也是能端上桌的一顿饭
        ("凉皮", "半成品加工"),
        ("半成品意面", "半成品加工"),
        ("炸薯条", "半成品加工"),
        ("空气炸锅羊排", "半成品加工"),
        ("空气炸锅鸡翅中", "半成品加工"),
        ("速冻水饺", "半成品加工"),
        ("速冻汤圆", "半成品"),
        ("速冻馄饨", "半成品加工"),
        ("红烧肉", "家常菜"),
        ("番茄炒蛋", "家常菜"),
        ("可乐鸡翅", "荤菜"),
        ("清炒时蔬", "素菜"),
        ("紫菜蛋花汤", "汤与粥"),
        # 最容易踩的假阳性: 做法词/配料词长得像非菜
        ("可乐炒饭", "主食"),
        ("啤酒鸭", "荤菜"),
        ("阳朔啤酒鱼", "水产"),
        ("乡村啤酒鸭", "荤菜"),
        ("酱牛肉", "荤菜"),
        ("酱排骨", "荤菜"),
        ("酱炖蟹", "水产"),
        ("炸酱面", "主食"),
        ("葱油拌面", "主食"),
        ("葱油桂鱼", "水产"),
        ("猪油拌饭", "主食"),
        ("黄油鸡", "荤菜"),
        ("芥末黄油罗氏虾", "水产"),
        ("牛奶粥", None),
        ("手工水饺", "主食"),
        ("空气炸锅面包片", "早餐"),
        ("微波炉蛋糕", "早餐"),
        ("小酥肉", "荤菜"),
        ("醪糟小汤圆", "主食"),
        ("糖醋排骨", "荤菜"),
        ("奶油蘑菇汤", "汤羹"),
    ],
)
def test_real_dishes_survive(name, cuisine):
    assert guess_is_dish(recipe(name, cuisine)) is True


def test_drink_keywords_never_kill_the_dish_they_are_cooked_with():
    """「可乐」「啤酒」是做法词而不是结论 —— 这是最容易踩的一处假阳性"""
    assert guess_is_dish(recipe("可乐鸡翅", None)) is True
    assert guess_is_dish(recipe("可乐桶", None)) is False


def test_sauce_is_caught_even_though_its_category_looks_like_a_dish():
    """番茄红酱的 cuisine/category 都被填成了「荤菜」—— 正说明现有分类不可信"""
    assert guess_is_dish(recipe("番茄红酱", "荤菜")) is False
    assert guess_is_dish(recipe("番茄牛腩", "荤菜")) is True


# --------------------------------------------------------------------------- 旁路的闸门不许掉


# 除了「饭决」主链路, 还有三条路径会各自 SELECT 一次 recipe。它们在集成测试里才跑得
# 起来(要 MySQL), 这里先用源码级断言钉住: 谁把 dish_only() 删了, 单测就先红。
def _calls_dish_only(method) -> bool:
    """按 AST 找 dish_only() 调用, 而不是按文本 —— 否则给函数写一句带这个词
    的 docstring 就能让检查假绿"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    return any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "dish_only"
        for node in ast.walk(tree)
    )


@pytest.mark.parametrize(
    "service, method",
    [
        (FridgeMenuService, "_load_candidates"),
        (ReplacementService, "_pick_local"),
        (MenuGenerationPipeline, "_load_local_candidates"),
        (DecisionService, "load_candidates"),
    ],
)
def test_every_candidate_loader_applies_the_shared_gate(service, method):
    assert _calls_dish_only(getattr(service, method)), (
        f"{service.__name__}.{method} 漏了 is_dish 闸门 —— "
        "别复制一份条件进来, 直接复用 dish_rules.dish_only()"
    )


def test_shared_gate_treats_null_as_a_dish():
    """NULL 一律放行: 少一道菜是事故, 多一道奶茶只是尴尬"""
    from sqlalchemy.dialects import mysql

    compiled = str(dish_only().compile(dialect=mysql.dialect()))
    assert "coalesce" in compiled.lower()
    assert "is_dish" in compiled


# --------------------------------------------------------------------------- 缺字段就是放行


def test_unknown_defaults_to_true():
    """判不了就放行: 漏判一次只是尴尬, 错杀一道菜是用户永远吃不到它"""
    assert is_dish_flag(None) is True
    assert is_dish_flag(True) is True
    assert is_dish_flag(1) is True
    assert is_dish_flag(False) is False
    assert is_dish_flag(0) is False


def test_empty_name_or_unknown_cuisine_is_kept():
    assert guess_is_dish(recipe("", None)) is True
    assert guess_is_dish(recipe("一道还没起名字的菜", None)) is True
