"""配置装配的单元测试

重点防一类很难发现的坑: pydantic 默认静默忽略不认识的键, 于是 .env 里
APP__AUTH__DEV_LOGIN 写错成别的名字不会报错, 只是"配置好像没生效"。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from app import config as app_config_module
from app.config import (
    Settings,
    deep_merge,
    env_overrides,
    find_unknown_settings_keys,
    load_yaml_defaults,
)

# 仓库根 = backend/app/config.py -> backend/app -> backend -> 仓库根
REPO_ROOT = Path(app_config_module.__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _settings(env: dict) -> Settings:
    return Settings.model_validate(deep_merge(load_yaml_defaults(), env_overrides(env)))


# ---------- 环境变量展开 ----------


def test_env_overrides_expands_nested_keys():
    data = env_overrides(
        {
            "APP__AUTH__COOKIE_SECURE": "false",
            "APP__APP__CORS_ORIGINS": '["https://a.example.com"]',
            "APP__APP__NAME": "我的菜谱",
            "APP__SCHEDULER__ENABLED": "true",
            "OTHER__IGNORED": "x",
        }
    )
    assert data == {
        "auth": {"cookie_secure": False},
        "app": {"cors_origins": ["https://a.example.com"], "name": "我的菜谱"},
        "scheduler": {"enabled": True},
    }


# ---------- 关键开关真的接上了 (回归: 曾经 APP__AUTH__DEV_LOGIN 是失效的) ----------


@pytest.mark.parametrize(
    ("env", "attr", "expected"),
    [
        ({"APP__AUTH__DEV_LOGIN": "true"}, "dev_login", True),
        ({"APP__AUTH__DEV_LOGIN": "false"}, "dev_login", False),
        ({"APP__AUTH__COOKIE_SECURE": "false"}, "cookie_secure", False),
        ({"APP__AUTH__JWT_SECRET": "s3cret"}, "jwt_secret", "s3cret"),
    ],
)
def test_auth_env_flags_are_applied(env, attr, expected):
    assert getattr(_settings(env).auth, attr) == expected


def test_scheduler_env_flags_are_applied():
    settings = _settings(
        {"APP__SCHEDULER__ENABLED": "true", "APP__SCHEDULER__TIMEZONE": "UTC"}
    )
    assert settings.scheduler.enabled is True
    assert settings.scheduler.timezone == "UTC"


def test_dev_login_is_off_without_env():
    assert _settings({}).auth.dev_login is False


# ---------- 拼写错误告警 ----------


def test_unknown_keys_are_reported():
    data = deep_merge(
        load_yaml_defaults(),
        env_overrides({"APP__AUTH__DEV_LOGIN_ENABLED": "true", "APP__FOO__BAR": "1"}),
    )
    assert find_unknown_settings_keys(data, Settings) == ["auth__dev_login_enabled", "foo"]


def test_known_keys_are_not_reported():
    assert find_unknown_settings_keys(load_yaml_defaults(), Settings) == []


def test_env_example_has_no_unknown_keys():
    """`.env.example` 是用户照抄的模板, 里面的每个键都必须真实存在"""
    env = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.startswith("APP__"):
            env[key.strip()] = value.strip()
    assert env, "没能从 .env.example 里解析出任何 APP__ 配置"

    data = deep_merge(load_yaml_defaults(), env_overrides(env))
    assert find_unknown_settings_keys(data, Settings) == []
