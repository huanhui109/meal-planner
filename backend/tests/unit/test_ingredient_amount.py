"""用量归一化单元测试"""
from __future__ import annotations

import pytest
from app.services.ingredient_amount import convert_quantity, normalize_amount, normalize_unit


@pytest.mark.parametrize(
    ("raw", "standard_unit", "expected_qty", "expected_unit"),
    [
        ("2个", "个", 2.0, "个"),
        ("200g", "g", 200.0, "g"),
        ("0.5kg", "g", 0.5, "kg"),
        ("2-3个", "个", 2.0, "个"),
        ("1.5斤", "斤", 1.5, "斤"),
        ("适量", "g", None, "g"),
        ("少许", "g", None, "g"),
        ("半根", "根", None, "根"),
        ("", "个", None, "个"),
        ("3 个", "个", 3.0, "个"),
        ("200克", "g", 200.0, "g"),
        ("100毫升", "ml", 100.0, "ml"),
        ("两枚", "个", None, "个"),
    ],
)
def test_normalize_amount(raw, standard_unit, expected_qty, expected_unit):
    result = normalize_amount(raw, standard_unit)
    assert result.quantity == expected_qty
    assert result.unit == expected_unit


def test_normalize_amount_accepts_numbers():
    """LLM 直接返回数字时不应被当成文本"""
    result = normalize_amount(200, "g")
    assert result.quantity == 200.0
    assert result.unit == "g"
    assert result.text == "200"


def test_normalize_amount_keeps_original_text():
    assert normalize_amount("2-3个", "个").text == "2-3个"
    assert normalize_amount("适量", "g").text == "适量"


def test_normalize_amount_truncates_long_text():
    assert len(normalize_amount("很长的描述" * 20, "g").text) <= 50


def test_normalize_unit_maps_aliases():
    assert normalize_unit("克") == "g"
    assert normalize_unit("公斤") == "kg"
    assert normalize_unit("只") == "个"
    assert normalize_unit("", "个") == "个"
    assert normalize_unit("自定义单位") == "自定义单位"


@pytest.mark.parametrize(
    ("quantity", "source", "target", "expected"),
    [
        (1, "kg", "g", 1000.0),
        (1000, "g", "kg", 1.0),
        (1, "斤", "g", 500.0),
        (2, "个", "个", 2.0),
        (2, "个", "g", None),
        (None, "g", "kg", None),
    ],
)
def test_convert_quantity(quantity, source, target, expected):
    assert convert_quantity(quantity, source, target) == expected
