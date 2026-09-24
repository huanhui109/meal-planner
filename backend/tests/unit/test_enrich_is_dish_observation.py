"""富集落库的 is_dish 观测单测 —— 关键是证明它**没有牙齿**

这个任务容易做成两件事里的错的那件: 顺手把判成非菜的菜挡下来。凌晨 03:30 无人值守,
自动拦截的误杀是静默且不可逆的 —— 用户少一道菜, 而日志里只会多一行"正常"。所以这组
用例里, **"仍然放行"的断言比"判定正确"的断言更重要**: 前者错了是事故, 后者错了只是
多一道奶茶。
"""
from __future__ import annotations

import ast
import inspect
import logging
import textwrap
from unittest.mock import MagicMock

import pytest
from app.models.recipe import EnrichKind, EnrichSource, EnrichStatus, Recipe
from app.services.recipe_enrich_service import (
    EnrichOutcome,
    RecipeEnrichService,
    _non_dish_bucket,
)


def svc() -> RecipeEnrichService:
    """session 用替身: 观测只往里 add 流水行, 不需要真库"""
    return RecipeEnrichService(session=MagicMock())


def recipe(name: str, cuisine: str | None = None, is_dish: bool = True) -> Recipe:
    r = Recipe(name=name, cuisine=cuisine, source="ai_generated",
               enrich_status=EnrichStatus.PENDING, enrich_source=EnrichSource.LLM)
    r.is_dish = is_dish
    return r


# --------------------------------------------------------------------------- 判定


@pytest.mark.parametrize(
    "name, cuisine",
    [
        ("油泼辣子", "调味品"),
        ("B52轰炸机", "饮品"),
        ("酸梅汤", "饮品"),
        ("提拉米苏", "甜品"),
        ("番茄红酱", "荤菜"),  # category/cuisine 都不可信的典型
    ],
)
def test_non_dish_is_recorded(name, cuisine):
    service, out = svc(), EnrichOutcome(kind=EnrichKind.EXPAND)
    service._observe_is_dish(recipe(name, cuisine), EnrichKind.EXPAND, out)
    assert name in out.non_dish


def test_normal_dish_records_nothing():
    service, out = svc(), EnrichOutcome(kind=EnrichKind.EXPAND)
    r = recipe("红烧肉", "荤菜")
    service._observe_is_dish(r, EnrichKind.EXPAND, out)

    assert out.non_dish == []
    assert out.non_dish_kinds == {}
    assert r.is_dish is True
    assert service.session.add.call_count == 0


# --------------------------------------------------------------------------- 绝不能拦截


@pytest.mark.parametrize("name, cuisine", [("油泼辣子", "调味品"), ("B52轰炸机", "饮品")])
def test_non_dish_is_still_let_through(name, cuisine):
    """判成非菜也**不许**改 is_dish —— 本轮是纯观测"""
    service, out = svc(), EnrichOutcome(kind=EnrichKind.EXPAND)
    r = recipe(name, cuisine, is_dish=True)
    service._observe_is_dish(r, EnrichKind.EXPAND, out)

    assert r.is_dish is True, "本期只观测, 谁在这里置 0 就是在凌晨静默杀死一道菜"
    assert out.non_dish == [name]


def test_warning_log_carries_the_dish_name(caplog):
    """日志里必须能看见菜名 —— 否则观测等于没观测"""
    service, out = svc(), EnrichOutcome(kind=EnrichKind.EXPAND)
    with caplog.at_level(logging.WARNING):
        service._observe_is_dish(recipe("油泼辣子", "调味品"), EnrichKind.EXPAND, out)
    assert "油泼辣子" in caplog.text


def test_enrich_log_row_records_both_values():
    """is_dish_guess 与实际写库值都要留下, 否则将来算不出不一致率"""
    service, out = svc(), EnrichOutcome(kind=EnrichKind.EXPAND)
    service._observe_is_dish(recipe("酸梅汤", "饮品"), EnrichKind.EXPAND, out, "rule")

    row = service.session.add.call_args[0][0]
    assert "is_dish_guess=0" in row.message
    assert "is_dish=1" in row.message


# --------------------------------------------------------------------------- 分桶计数


@pytest.mark.parametrize(
    "name, cuisine, bucket",
    [
        ("B52轰炸机", "饮品", "饮品"),
        ("提拉米苏", "甜品", "甜品"),
        ("油泼辣子", "调味品", "其他"),
        ("番茄红酱", "荤菜", "其他"),
    ],
)
def test_drink_and_dessert_are_counted_apart(name, cuisine, bucket):
    """饮品/甜品占 54 道非菜的 78%, 且边界最模糊, 必须单独看"""
    out = EnrichOutcome(kind=EnrichKind.EXPAND)
    svc()._observe_is_dish(recipe(name, cuisine), EnrichKind.EXPAND, out)
    assert out.non_dish_kinds == {bucket: 1}
    assert _non_dish_bucket(recipe(name, cuisine)) == bucket


def test_ratio_over_scanned():
    out = EnrichOutcome(kind=EnrichKind.EXPAND, scanned=10)
    service = svc()
    service._observe_is_dish(recipe("油泼辣子", "调味品"), EnrichKind.EXPAND, out)
    assert out.non_dish_ratio == pytest.approx(0.1)


def test_ratio_is_zero_without_scans():
    assert EnrichOutcome().non_dish_ratio == 0.0


# --------------------------------------------------------------------------- 别刷屏


def test_already_zero_rows_are_consistent_and_silent():
    """那 54 道已置 0 的非菜: 判 0 存 0 = 一致, 不该每轮重复告警"""
    service, out = svc(), EnrichOutcome(kind=EnrichKind.FIELDS)
    service._observe_is_dish(recipe("油泼辣子", "调味品", is_dish=False),
                             EnrichKind.FIELDS, out)
    assert out.non_dish == []
    assert service.session.add.call_count == 0


def test_manually_restored_non_dish_is_reported():
    """人工校正把某道非菜改回 1 的(比如主理人认为它该进候选): 判 0 存 1 = 不一致,
    这条必须报出来 —— 它不是错误, 是"规则和人工意见不同", 正是要看的东西"""
    service, out = svc(), EnrichOutcome(kind=EnrichKind.FIELDS)
    service._observe_is_dish(recipe("提拉米苏", "甜品", is_dish=True),
                             EnrichKind.FIELDS, out)
    assert out.non_dish == ["提拉米苏"]


# --------------------------------------------------------------------------- 批次汇总


def test_outcome_dict_carries_the_observation():
    out = EnrichOutcome(kind=EnrichKind.EXPAND, scanned=4)
    svc()._observe_is_dish(recipe("奶茶", "饮品"), EnrichKind.EXPAND, out)
    payload = out.to_dict()
    assert payload["non_dish"] == ["奶茶"]
    assert payload["non_dish_kinds"] == {"饮品": 1}
    assert payload["non_dish_ratio"] == 0.25


# --------------------------------------------------------------------------- 钩子不许掉


def _calls_observe(method) -> bool:
    """按 AST 找调用, 而不是按文本 —— 否则在 docstring 里提一句就能让检查假绿"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    return any(
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "_observe_is_dish"
        for node in ast.walk(tree)
    )


@pytest.mark.parametrize("method", ["expand", "_run"])
def test_observation_is_hooked_on_every_write_path(method):
    """只测辅助函数等于没测 —— 钩子哪天在重构里被摘掉, 观测会静默归零

    「观测静默归零」是最坏的一种失效: 它不报错、不告警, 只是以后再也没数据,
    等你想起来要看不一致率时, 发现从某天起就是空的。
    """
    assert _calls_observe(getattr(RecipeEnrichService, method)), (
        f"RecipeEnrichService.{method} 没有调用 _observe_is_dish —— "
        "新菜落库是唯一能提前看见「柠檬蜂蜜水」的地方, 观测不能只挂在半条路上"
    )
