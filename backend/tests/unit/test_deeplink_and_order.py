"""单元测试: 补单出口的链接生成与补单决策 (纯逻辑, 不碰数据库)

这两个模块最容易出的错是"看起来有数, 其实是假的": 链接拼错、凑单凑出了负数、
没有参考价的食材被当成 0 元计入合计。下面每个断言都对应一条这样的坑。
"""
from __future__ import annotations

from app.config import Settings, deep_merge, env_overrides, load_yaml_defaults
from app.services.deeplink_service import PLATFORM_MEITUAN, PLATFORM_XIAOXIANG, DeeplinkService
from app.services.order_service import OrderService


def _settings(env: dict | None = None) -> Settings:
    return Settings.model_validate(deep_merge(load_yaml_defaults(), env_overrides(env or {})))


def _item(name: str, *, deficit, unit="个", price=None, ingredient_id=1, quantitative=True) -> dict:
    return {
        "ingredient_id": ingredient_id,
        "name": name,
        "category": "蔬菜",
        "unit": unit,
        "deficit": deficit,
        "reference_price": price,
        "quantitative": quantitative,
        "have_enough": False,
    }


def _shopping(items: list) -> dict:
    return {"items": items, "summary": {"to_buy_count": len(items), "have_count": 0}}


# ---------- DeeplinkService ----------


def test_search_link_encodes_keyword():
    service = DeeplinkService(_settings())
    link = service.search_link("西红柿")
    assert link.startswith("https://")
    assert "%E8%A5%BF%E7%BA%A2%E6%9F%BF" in link
    assert "{keyword}" not in link


def test_search_link_falls_back_to_base_url_without_keyword():
    service = DeeplinkService(_settings())
    link = service.search_link("   ")
    assert "{keyword}" not in link
    assert not link.endswith("/")


def test_search_link_supports_template_without_placeholder():
    settings = _settings({"APP__PLATFORMS__XIAOXIANG__SEARCH_TEMPLATE": "https://shop.example.com/s?q="})
    link = DeeplinkService(settings).search_link("鸡蛋")
    assert link.startswith("https://shop.example.com/s?q=")
    assert link.endswith("%E9%B8%A1%E8%9B%8B")


def test_multi_item_links_deduplicates_by_name():
    service = DeeplinkService(_settings())
    links = service.multi_item_links(["西红柿", "西红柿", " 鸡蛋 ", ""])
    assert [entry["name"] for entry in links] == ["西红柿", "鸡蛋"]
    assert all(entry["platform"] == PLATFORM_XIAOXIANG for entry in links)


def test_each_platform_uses_its_own_template():
    settings = _settings({"APP__PLATFORMS__MEITUAN_WAIMAI__SEARCH_TEMPLATE": "https://wm.example.com/s?q={keyword}"})
    service = DeeplinkService(settings)
    assert service.search_link("鸡蛋", PLATFORM_MEITUAN).startswith("https://wm.example.com/")
    assert service.search_link("鸡蛋").startswith("https://i.waimai.meituan.com/")
    assert service.min_order_amount() == 20.0
    assert service.min_order_amount(PLATFORM_MEITUAN) == 0.0


def test_shopping_link_joins_first_six_names():
    service = DeeplinkService(_settings())
    link = service.shopping_link([f"食材{i}" for i in range(8)])
    assert link.count("%20") == 5  # 6 个词之间有 5 个空格


# ---------- OrderService ----------


def test_order_estimates_price_from_deficit_times_reference_price():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(_shopping([_item("西红柿", deficit=2, price=2.25)]))
    assert result["estimated_total"] == 4.5
    assert result["items"][0]["estimated_price"] == 4.5
    assert result["missing_count"] == 1


def test_order_returns_none_without_deficit():
    service = OrderService(DeeplinkService(_settings()))
    assert service.build_suggestion(_shopping([])) is None
    assert service.build_suggestion(None) is None


def test_order_flags_unpriced_items_and_excludes_them_from_total():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(_shopping([_item("神秘香料", deficit=1, price=None)]))
    assert result["estimated_total"] == 0.0
    assert result["unpriced_count"] == 1
    assert result["items"][0]["estimated_price"] is None
    assert "参考价" in result["note"]


def test_order_marks_unquantified_item_without_price():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping([_item("盐", deficit=None, unit="g", price=0.01, quantitative=False)])
    )
    assert result["items"][0]["estimated_price"] is None
    assert result["items"][0]["quantity"] is None


def test_order_adds_topup_items_until_min_order_reached():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping(
            [
                _item("西红柿", deficit=2, price=2.0, ingredient_id=1),
                _item("鸡蛋", deficit=6, price=1.5, ingredient_id=2),
            ]
        ),
        today_ingredient_ids=[1],
    )
    assert result["items"][0]["name"] == "西红柿"
    assert result["items"][0]["is_topup"] is False
    topup = [line for line in result["items"] if line["is_topup"]]
    assert [line["name"] for line in topup] == ["鸡蛋"]
    assert result["estimated_total"] == 13.0
    assert result["min_order_amount"] == 20.0
    assert result["reaches_min_order"] is False
    assert result["topup_amount"] == 7.0
    assert "起送价" in result["note"]


def test_order_never_topups_with_a_much_pricier_item():
    """凑单可以略超起送价, 但不能为了凑 2 元去多加一份 40 元的排骨"""
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping(
            [
                _item("西红柿", deficit=3, price=3.0, ingredient_id=1),  # 9
                _item("鸡蛋", deficit=6, price=1.5, ingredient_id=2),  # 9 -> 18
                _item("排骨", deficit=1, price=40.0, ingredient_id=3),  # 太贵, 不该加
            ]
        ),
        today_ingredient_ids=[1],
    )
    topup = [line["name"] for line in result["items"] if line["is_topup"]]
    assert topup == ["鸡蛋"]
    assert result["estimated_total"] == 18.0
    assert result["reaches_min_order"] is False
    assert result["topup_amount"] == 2.0


def test_order_stops_adding_topup_once_min_order_reached():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping(
            [
                _item("西红柿", deficit=6, price=3.0, ingredient_id=1),  # 18
                _item("鸡蛋", deficit=1, price=1.5, ingredient_id=2),  # 1.5 -> 19.5
                _item("小葱", deficit=1, price=2.0, ingredient_id=3),  # 21.5 够了
                _item("排骨", deficit=1, price=9.0, ingredient_id=4),
            ]
        ),
        today_ingredient_ids=[1],
    )
    topup = [line["name"] for line in result["items"] if line["is_topup"]]
    assert topup == ["鸡蛋", "小葱"]
    assert result["reaches_min_order"] is True
    assert result["topup_amount"] == 0.0


def test_order_marks_out_of_budget():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping([_item("排骨", deficit=1, price=40.0)]), budget_remaining=12.0
    )
    assert result["within_budget"] is False
    assert result["budget_remaining"] == 12.0


def test_order_without_min_order_configured_skips_topup():
    settings = _settings({"APP__PLATFORMS__XIAOXIANG__MIN_ORDER_AMOUNT": "0"})
    service = OrderService(DeeplinkService(settings))
    result = service.build_suggestion(
        _shopping([_item("西红柿", deficit=1, price=1.0, ingredient_id=1), _item("鸡蛋", deficit=1, price=1.5, ingredient_id=2)]),
        today_ingredient_ids=[1],
    )
    assert all(not line["is_topup"] for line in result["items"])
    assert result["reaches_min_order"] is True


def test_order_falls_back_to_all_items_when_today_ids_unknown():
    service = OrderService(DeeplinkService(_settings()))
    result = service.build_suggestion(
        _shopping([_item("西红柿", deficit=1, price=1.0, ingredient_id=1)]), today_ingredient_ids=[]
    )
    assert result["missing_count"] == 1
    assert result["items"][0]["is_topup"] is False
