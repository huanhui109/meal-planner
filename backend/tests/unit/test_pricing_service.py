"""成本估算单元测试"""
from __future__ import annotations

from app.services.pricing_service import PricedRow, PricingService

service = PricingService()


def row(name="牛肉", quantity=200.0, unit="g", price=0.06, standard_unit="g") -> PricedRow:
    return PricedRow(
        ingredient_name=name,
        quantity=quantity,
        unit=unit,
        reference_price=price,
        standard_unit=standard_unit,
    )


def test_simple_multiplication():
    estimate = service.estimate([row()])
    assert estimate.total == 12.0
    assert estimate.priced_items == 1


def test_unit_conversion_applies():
    """菜谱单位 kg, 参考价按 g 计"""
    estimate = service.estimate([row(quantity=0.5, unit="kg", price=0.02, standard_unit="g")])
    assert estimate.total == 10.0


def test_unquantified_is_counted_but_not_guessed():
    estimate = service.estimate([row(name="盐", quantity=None, price=0.003)])
    assert estimate.total == 0.0
    assert estimate.unpriced_items == 1
    assert estimate.unpriced_names == ["盐"]


def test_missing_price_is_counted_as_unpriced():
    estimate = service.estimate([row(name="神秘食材", price=None)])
    assert estimate.unpriced_items == 1


def test_incompatible_units_are_not_priced():
    estimate = service.estimate([row(quantity=2, unit="个", price=1.5, standard_unit="g")])
    assert estimate.total == 0.0
    assert estimate.unpriced_items == 1


def test_total_is_rounded_to_cents():
    estimate = service.estimate([row(quantity=333.33, unit="g", price=0.0333, standard_unit="g")])
    assert estimate.total == round(333.33 * 0.0333, 2)
