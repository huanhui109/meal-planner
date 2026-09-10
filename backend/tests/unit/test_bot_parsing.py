"""飞书 Bot 指令解析与调度时间解析的单元测试 (纯函数, 不连数据库)"""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from app.bot.command_handler import (
    BotReply,
    parse_add_inventory,
    parse_command,
    parse_meal_target,
)
from app.bot.webhook_security import (
    calculate_signature,
    decrypt_event,
    encrypt_event,
    is_encrypted,
    verify_signature,
    verify_token,
)
from app.scheduler.scheduler_manager import build_trigger

TODAY = date(2026, 1, 7)
SHANGHAI = ZoneInfo("Asia/Shanghai")


# ---------- parse_command ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("菜单", "菜单"),
        ("查看今天菜单", "菜单"),
        ("今日菜单", "菜单"),
        ("库存", "库存"),
        ("查看库存", "库存"),
        ("添加库存 鸡蛋 10个", "添加库存"),
        ("入库 排骨 2斤", "添加库存"),
        ("完成 今天晚餐", "完成"),
        ("做好了 周三午餐", "完成"),
        ("帮助", "帮助"),
        ("help", "help"),
        ("?", "?"),
        ("今天天气怎么样", "今天天气怎么样"),
        ("   ", ""),
    ],
)
def test_parse_command(raw, expected):
    assert parse_command(raw) == expected


# ---------- parse_add_inventory ----------


def test_parse_add_inventory_with_expiry():
    parsed = parse_add_inventory("添加库存 鸡蛋 10个 保质期 2026-01-20", TODAY)
    assert parsed == {
        "name": "鸡蛋",
        "quantity": 10.0,
        "unit": "个",
        "expiry_date": date(2026, 1, 20),
    }


def test_parse_add_inventory_split_unit():
    parsed = parse_add_inventory("入库 排骨 2 斤", TODAY)
    assert parsed["name"] == "排骨"
    assert parsed["quantity"] == 2.0
    assert parsed["unit"] == "斤"
    assert parsed["expiry_date"] is None


def test_parse_add_inventory_decimal_quantity():
    parsed = parse_add_inventory("添加库存 牛奶 1.5L", TODAY)
    assert parsed["quantity"] == 1.5
    assert parsed["unit"] == "L"


def test_parse_add_inventory_short_expiry_date():
    parsed = parse_add_inventory("添加库存 菠菜 500g 保质期 01-15", TODAY)
    assert parsed["expiry_date"] == date(2026, 1, 15)


@pytest.mark.parametrize(
    "raw",
    [
        "添加库存 鸡蛋",
        "添加库存 鸡蛋 适量",
        "添加库存",
        "添加库存 鸡蛋 0个",
        "",
    ],
)
def test_parse_add_inventory_returns_none_when_unparsable(raw):
    assert parse_add_inventory(raw, TODAY) is None


# ---------- parse_meal_target ----------


@pytest.mark.parametrize(
    ("raw", "expected_date", "expected_meal"),
    [
        ("完成 今天晚餐", TODAY, "dinner"),
        ("完成 今晚晚饭", TODAY, "dinner"),
        ("完成 昨天早餐", date(2026, 1, 6), "breakfast"),
        ("完成 明天午餐", date(2026, 1, 8), "lunch"),
        ("完成 周三午餐", date(2026, 1, 7), "lunch"),
        ("完成 周日午饭", date(2026, 1, 11), "lunch"),
        ("完成 2026-01-09 晚餐", date(2026, 1, 9), "dinner"),
        ("完成 午餐", TODAY, "lunch"),
    ],
)
def test_parse_meal_target(raw, expected_date, expected_meal):
    assert parse_meal_target(raw, TODAY) == (expected_date, expected_meal)


@pytest.mark.parametrize("raw", ["完成", "今天天气", "周三"])
def test_parse_meal_target_returns_none_without_meal(raw):
    assert parse_meal_target(raw, TODAY) == (None, None)


# ---------- BotReply ----------


def test_bot_reply_text_payload():
    reply = BotReply.text("你好")
    assert reply.msg_type == "text"
    assert reply.to_payload() == {"msg_type": "text", "content": '{"text": "你好"}'}


# ---------- 调度时间解析 ----------


def test_build_trigger_daily_time():
    trigger = build_trigger("08:00", SHANGHAI)
    assert trigger is not None
    assert str(trigger) == "cron[hour='8', minute='0']"


def test_build_trigger_weekly_time():
    trigger = build_trigger("SUN 20:00", SHANGHAI)
    assert trigger is not None
    assert "day_of_week='sun'" in str(trigger)


def test_build_trigger_five_field_crontab():
    trigger = build_trigger("30 17 * * 1-5", SHANGHAI)
    assert trigger is not None
    assert "day_of_week='1-5'" in str(trigger)


@pytest.mark.parametrize("spec", ["", "   ", "off", "OFF", "none", "disabled", "false"])
def test_build_trigger_disabled_specs(spec):
    assert build_trigger(spec, SHANGHAI) is None


@pytest.mark.parametrize("spec", ["25:00", "08:60", "FUN 08:00", "abc", "08:00 extra words here"])
def test_build_trigger_rejects_invalid_specs(spec):
    with pytest.raises(ValueError):
        build_trigger(spec, SHANGHAI)


# ---------- 飞书回调安全 (签名/加解密) ----------


def test_verify_signature_passes_without_encrypt_key():
    assert verify_signature({}, "") is True


def test_verify_signature_accepts_correct_signature():
    timestamp = "1735689600"
    encrypt_key = "test-encrypt-key"
    signature = calculate_signature(timestamp, encrypt_key)
    headers = {"X-Lark-Signature": signature, "X-Lark-Request-Timestamp": timestamp}
    assert verify_signature(headers, encrypt_key) is True
    assert verify_signature({}, encrypt_key) is False
    assert verify_signature({"X-Lark-Signature": "bad", "X-Lark-Request-Timestamp": timestamp}, encrypt_key) is False


def test_verify_token_allows_when_not_configured():
    assert verify_token({}, "") is True
    assert verify_token({"token": "abc"}, "abc") is True
    assert verify_token({"token": "abc"}, "other") is False
    assert verify_token({}, "abc") is False
    assert verify_token({"header": {"token": "abc"}}, "abc") is True


def test_encrypt_decrypt_round_trip():
    payload = {"type": "event_callback", "token": "tok", "event": {"type": "im.message.receive_v1"}}
    envelope = encrypt_event(payload, "test-encrypt-key")
    assert is_encrypted(envelope) is True
    assert decrypt_event(envelope["encrypt"], "test-encrypt-key") == payload


def test_decrypt_rejects_wrong_key():
    envelope = encrypt_event({"a": 1}, "key-a")
    with pytest.raises(ValueError):
        decrypt_event(envelope["encrypt"], "key-b")


def test_decrypt_rejects_garbage():
    with pytest.raises(ValueError):
        decrypt_event("not-base64!!", "key-a")
