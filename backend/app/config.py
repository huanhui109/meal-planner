"""应用配置模块 - YAML 默认值 + .env/环境变量覆盖

优先级: 环境变量 (APP__ 前缀, __ 分隔) > .env 文件 > config/default.yaml > 代码默认值
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "APP__"
ENV_NESTED_DELIMITER = "__"


class AppSettings(BaseModel):
    """应用基础配置"""
    name: str = "AI 每周营养菜谱工具"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    base_url: str = "http://127.0.0.1:8000"
    cors_origins: List[str] = Field(default_factory=list)


class DatabaseSettings(BaseModel):
    """数据库配置 (MySQL 8.0 / utf8mb4)"""
    url: str = "mysql+aiomysql://meal_planner:change-me@127.0.0.1:3306/meal_planner?charset=utf8mb4"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_recycle: int = 1800
    pool_timeout: int = 30


class AuthSettings(BaseModel):
    """认证与 Cookie 配置"""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 120
    refresh_token_days: int = 30
    cookie_secure: bool = True
    cookie_domain: str = ""
    access_cookie_name: str = "mp_access"
    refresh_cookie_name: str = "mp_refresh"
    dev_login_enabled: bool = False


class MenuSettings(BaseModel):
    """菜单生成配置"""
    daily_generation_limit: int = 3
    generation_concurrency: int = 2
    task_timeout_seconds: int = 900
    history_weeks: int = 4
    diversity_min_score: float = 0.7
    budget_tolerance: float = 0.05


class SchedulerSettings(BaseModel):
    """调度器配置 (定时任务在二期实现)"""
    db_url: str = ""
    daily_menu_push: str = "08:00"
    evening_check: str = "17:30"
    weekly_generation: str = "SUN 20:00"
    daily_scrape: str = "09:00"
    expiry_check: str = "10:00"


class LLMProviderSettings(BaseModel):
    """LLM 提供商配置"""
    name: str = ""
    api_base: str = ""
    api_key: str = ""  # 仅由环境变量注入, 不落配置文件
    model: str = ""
    max_tokens: int = 6000


class LLMLocalSettings(BaseModel):
    """本地 LLM 配置"""
    enabled: bool = False
    model_path: str = "qwen2.5-7b-instruct-4bit"
    server_port: int = 8080


class LLMSettings(BaseModel):
    """LLM 总配置"""
    primary: LLMProviderSettings = LLMProviderSettings()
    fallbacks: List[LLMProviderSettings] = Field(default_factory=list)
    local: LLMLocalSettings = LLMLocalSettings()
    monthly_budget_cny: float = 50.0
    rate_limit_qps: int = 5
    demo_mode: bool = False


class FeishuSettings(BaseModel):
    """飞书开放平台配置"""
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    default_chat_id: str = ""
    redirect_uri: str = ""
    login_success_redirect: str = "/"


class PlatformXiaoxiangSettings(BaseModel):
    """小象超市配置"""
    enabled: bool = True
    base_url: str = "https://h5.waimai.meituan.com"


class PlatformMeituanSettings(BaseModel):
    """美团外卖配置"""
    enabled: bool = False
    base_url: str = "https://wm.waimai.meituan.com"


class PlatformSettings(BaseModel):
    """平台配置"""
    xiaoxiang: PlatformXiaoxiangSettings = PlatformXiaoxiangSettings()
    meituan_waimai: PlatformMeituanSettings = PlatformMeituanSettings()


class ScrapingSettings(BaseModel):
    """采集配置"""
    headless: bool = True
    timeout: int = 30000
    retry_count: int = 2
    retry_delay: int = 5


def _candidate_yaml_paths() -> List[Path]:
    """config/default.yaml 的可能位置 (仓库根 / backend 同级)"""
    here = Path(__file__).resolve()
    return [
        Path.cwd() / "config" / "default.yaml",
        here.parent.parent.parent / "config" / "default.yaml",  # backend/../
    ]


def load_yaml_defaults() -> Dict[str, Any]:
    """读取 YAML 默认值, 缺失时返回空 dict"""
    explicit = os.getenv("APP_CONFIG_FILE")
    candidates = [Path(explicit)] if explicit else _candidate_yaml_paths()
    for path in candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}


def _coerce_env_value(raw: str) -> Any:
    """把环境变量字符串还原成 Python 值 (尽量宽松)"""
    text = raw.strip()
    if text == "":
        return ""
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    return text


def env_overrides(environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """把 APP__A__B=v 形式的环境变量展开成嵌套 dict"""
    env = environ if environ is not None else dict(os.environ)
    result: Dict[str, Any] = {}
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX):].split(ENV_NESTED_DELIMITER)
        if not all(path):
            continue
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part.lower(), {})
        cursor[path[-1].lower()] = _coerce_env_value(value)
    return result


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并, override 优先"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings(BaseSettings):
    """全局应用配置"""
    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = AppSettings()
    database: DatabaseSettings = DatabaseSettings()
    auth: AuthSettings = AuthSettings()
    menu: MenuSettings = MenuSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    llm: LLMSettings = LLMSettings()
    feishu: FeishuSettings = FeishuSettings()
    platforms: PlatformSettings = PlatformSettings()
    scraping: ScrapingSettings = ScrapingSettings()

    @classmethod
    def load(cls) -> "Settings":
        """按 env > .env > yaml > 默认值 的顺序装配配置"""
        load_dotenv(override=False)
        data = deep_merge(load_yaml_defaults(), env_overrides())
        settings = cls.model_validate(data)
        settings.inject_secrets()
        settings.apply_derived_defaults()
        return settings

    def inject_secrets(self) -> None:
        """把密钥从独立环境变量注入 (避免写进 yaml)"""
        llm_key_map = {
            "glm-4": os.getenv("GLM4_API_KEY", ""),
            "qwen-max": os.getenv("QWEN_API_KEY", ""),
            "deepseek-chat": os.getenv("DEEPSEEK_API_KEY", ""),
        }
        if llm_key_map.get(self.llm.primary.name):
            self.llm.primary.api_key = llm_key_map[self.llm.primary.name]
        for provider in self.llm.fallbacks:
            if llm_key_map.get(provider.name):
                provider.api_key = llm_key_map[provider.name]

        self.feishu.app_id = os.getenv("FEISHU_APP_ID", self.feishu.app_id)
        self.feishu.app_secret = os.getenv("FEISHU_APP_SECRET", self.feishu.app_secret)
        self.feishu.verification_token = os.getenv("FEISHU_VERIFICATION_TOKEN", self.feishu.verification_token)
        self.feishu.encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", self.feishu.encrypt_key)
        self.feishu.default_chat_id = os.getenv("FEISHU_DEFAULT_CHAT_ID", self.feishu.default_chat_id)

        if not self.auth.jwt_secret:
            self.auth.jwt_secret = os.getenv("JWT_SECRET", "")

    def apply_derived_defaults(self) -> None:
        """补齐依赖其他字段的默认值"""
        if not self.scheduler.db_url:
            self.scheduler.db_url = self.database.url


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings.load()


def reset_settings_cache() -> None:
    """清空配置缓存 (测试用)"""
    get_settings.cache_clear()
