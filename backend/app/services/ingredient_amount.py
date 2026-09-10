"""用量文本归一化 - 把 LLM 返回的自由文本转成 数量 + 单位

规则:
  "2个"     -> quantity=2, unit=个
  "200g"    -> quantity=200, unit=g
  "2-3个"   -> quantity=2 (取下界), unit=个
  "适量"    -> quantity=None, unit=标准单位
  ""        -> quantity=None, unit=标准单位
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

MAX_UNIT_LENGTH = 20

NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
UNIT_PATTERN = re.compile(r"^\s*([A-Za-z\u4e00-\u9fff]{1,10})")

VAGUE_WORDS = ("适量", "少许", "少量", "若干", "按需", "酌情", "一些", "随意")

UNIT_ALIASES = {
    "克": "g", "公克": "g",
    "千克": "kg", "公斤": "kg",
    "毫升": "ml", "升": "l",
    "只": "个", "枚": "个",
    "棵": "颗",
    "汤匙": "勺", "茶匙": "小勺", "匙": "勺",
}


@dataclass(frozen=True)
class NormalizedAmount:
    """归一化后的用量"""
    quantity: Optional[float]
    unit: str
    text: str

    @property
    def is_vague(self) -> bool:
        return self.quantity is None


def normalize_unit(raw_unit: str, fallback: str = "") -> str:
    """单位归一化: 别名映射 -> 原值 -> 标准单位"""
    unit = (raw_unit or "").strip()
    if not unit:
        return fallback
    unit = UNIT_ALIASES.get(unit, unit)
    return unit[:MAX_UNIT_LENGTH]


def normalize_amount(
    raw_text: Optional[Union[str, float, int]], standard_unit: str = ""
) -> NormalizedAmount:
    """把一条用量文本归一化"""
    if isinstance(raw_text, (int, float)) and not isinstance(raw_text, bool):
        unit = normalize_unit(standard_unit)
        return NormalizedAmount(float(raw_text), unit, f"{raw_text:g}")
    text = str(raw_text or "").strip()
    fallback_unit = normalize_unit(standard_unit)
    if not text:
        return NormalizedAmount(None, fallback_unit, "")

    match = NUMBER_PATTERN.search(text)
    if not match:
        return NormalizedAmount(None, fallback_unit, text[:50])

    try:
        quantity = float(match.group(1))
    except ValueError:  # pragma: no cover - 正则已保证可解析
        return NormalizedAmount(None, fallback_unit, text[:50])

    remainder = text[match.end():].strip()
    unit_match = UNIT_PATTERN.match(remainder)
    raw_unit = unit_match.group(1) if unit_match else ""
    if raw_unit in VAGUE_WORDS:
        raw_unit = ""
    unit = normalize_unit(raw_unit, fallback_unit)
    return NormalizedAmount(quantity, unit, text[:50])


UNIT_CONVERSIONS = {
    ("kg", "g"): 1000.0,
    ("g", "kg"): 0.001,
    ("斤", "g"): 500.0,
    ("g", "斤"): 0.002,
    ("l", "ml"): 1000.0,
    ("ml", "l"): 0.001,
}


def convert_quantity(quantity: Optional[float], from_unit: str, to_unit: str) -> Optional[float]:
    """单位换算, 无法换算时返回 None"""
    if quantity is None:
        return None
    source = normalize_unit(from_unit)
    target = normalize_unit(to_unit)
    if not target or not source or source == target:
        return quantity
    factor = UNIT_CONVERSIONS.get((source, target))
    if factor is None:
        return None
    return quantity * factor
