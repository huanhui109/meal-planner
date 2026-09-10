"""单测: 第三方密钥的对称加密与掩码"""
from __future__ import annotations

import pytest
from app.services import secret_box


def test_roundtrip():
    token = secret_box.encrypt("cli_secret_value")
    assert token and token != "cli_secret_value"
    assert secret_box.decrypt(token) == "cli_secret_value"


def test_ciphertext_is_not_reversible_by_reading():
    """同一条明文两次加密得到不同密文 (Fernet 带随机 IV)"""
    assert secret_box.encrypt("same") != secret_box.encrypt("same")


def test_empty_values_pass_through():
    """空表示"没配", 不该产出密文也不该报错"""
    assert secret_box.encrypt("") == ""
    assert secret_box.encrypt(None) == ""
    assert secret_box.decrypt("") == ""
    assert secret_box.decrypt(None) == ""


def test_decrypt_rejects_foreign_token():
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.decrypt("not-a-fernet-token")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", ""),
        ("abc", "***"),
        ("cli_a1b2c3d4e5f6", "cli_******e5f6"),
    ],
)
def test_mask_keeps_only_edges(raw, expected):
    assert secret_box.mask(raw) == expected


def test_mask_never_leaks_middle():
    masked = secret_box.mask("cli_1234567890secret")
    assert "567890sec" not in masked
