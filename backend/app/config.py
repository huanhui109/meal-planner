"""应用配置模块 - YAML 默认值 + .env/环境变量覆盖

优先级: 环境变量 (APP__ 前缀, __ 分隔) > .env 文件 > config/default.yaml > 代码默认值
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, get_args, get_origin

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "APP__"
ENV_NESTED_DELIMITER = "__"

logger = logging.getLogger(__name__)


class AppSettings(BaseModel):
    """应用基础配置"""

    name: str = "每周鲜 · AI 营养菜谱"
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
    dev_login: bool = False


class MenuSettings(BaseModel):
    """菜单生成配置"""

    daily_generation_limit: int = 3
    # 重新生成 = 该周已有菜单、用户主动换一批。它和"首次生成"不是一回事:
    # 首次生成是探索, 重生成是常规的编辑动作, 共用一个 3 次上限会让用户改两下就被卡住。
    daily_regenerate_limit: int = 10
    generation_concurrency: int = 2
    task_timeout_seconds: int = 900
    history_weeks: int = 4
    diversity_min_score: float = 0.7
    budget_tolerance: float = 0.05
    # V2.3 本地菜谱库优先: 先用本地库编排, 填充率不足才交给 LLM
    local_first: bool = True
    local_min_fill: float = 0.8
    local_candidate_pool: int = 300


class SchedulerSettings(BaseModel):
    """推送调度器配置

    enabled 默认关闭: 多 worker 部署时每个 worker 都会注册一遍任务, 会重复推送,
    所以生产上要显式打开, 并且只让一个 worker 开 (见 deploy/README.md)。
    时间写法: "HH:MM" 每天, "SUN HH:MM" 每周某天, 或标准 5 段 crontab; 留空表示不注册该任务。
    """

    enabled: bool = False
    timezone: str = "Asia/Shanghai"
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


class LLMVisionSettings(BaseModel):
    """拍照识别 (冰箱入库) 用的视觉模型

    Key 不单独存: 视觉模型与文本模型同属一家时共用 llm.primary.api_key,
    api_base 留空也复用 primary 的地址。没配 Key 时 configured=False,
    接口返回 503, 前端把按钮置灰并引导手动添加, 不影响任何既有流程。
    """

    enabled: bool = True
    model: str = "glm-4v-flash"
    api_base: str = ""
    api_key: str = ""  # 仅由环境变量注入, 留空则复用 primary
    max_image_mb: float = 6.0
    max_edge_px: int = 1280
    daily_limit: int = 20
    max_tokens: int = 1500


class LLMSettings(BaseModel):
    """LLM 总配置"""

    primary: LLMProviderSettings = LLMProviderSettings()
    fallbacks: List[LLMProviderSettings] = Field(default_factory=list)
    local: LLMLocalSettings = LLMLocalSettings()
    vision: LLMVisionSettings = LLMVisionSettings()
    monthly_budget_cny: float = 50.0
    rate_limit_qps: int = 5
    demo: bool = False


class FeishuSettings(BaseModel):
    """飞书开放平台配置"""

    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    default_chat_id: str = ""
    redirect_uri: str = ""
    login_success_redirect: str = "/"


class WechatSettings(BaseModel):
    """微信小程序配置 (微信一键登录)"""

    app_id: str = ""
    app_secret: str = ""


class PlatformXiaoxiangSettings(BaseModel):
    """小象超市配置

    本期不采集商品, 只把"缺什么"变成"点一下就能去买": search_template 里的
    {keyword} 会被替换成 URL 编码后的食材名。小程序端如果配了 miniapp_app_id,
    还能直接 navigateToMiniProgram 打开小象超市小程序。
    """

    enabled: bool = True
    base_url: str = "https://h5.waimai.meituan.com"
    search_template: str = "https://i.waimai.meituan.com/search/?keyword={keyword}"
    miniapp_app_id: str = ""
    min_order_amount: float = 20.0
    delivery_note: str = ""


class PlatformMeituanSettings(BaseModel):
    """美团外卖配置 (自做 vs 外卖里的"点外卖"出口)"""

    enabled: bool = True
    base_url: str = "https://wm.waimai.meituan.com"
    search_template: str = "https://i.waimai.meituan.com/search/?keyword={keyword}"
    miniapp_app_id: str = ""
    min_order_amount: float = 0.0
    delivery_note: str = ""


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


class ProjKitchenSettings(BaseModel):
    """proj.kitchen 静态 JSON API 数据源"""

    enabled: bool = True
    index_url: str = "https://proj.kitchen/api/recipes"
    detail_url: str = "https://proj.kitchen/api/recipes/{id}"


class HowToCookSettings(BaseModel):
    """HowToCook 开源菜谱仓库"""

    enabled: bool = True
    repo_url: str = "https://github.com/Anduin2017/HowToCook"
    branch: str = "master"


class RecipeImportSettings(BaseModel):
    """开源菜谱导入配置 (scripts/import_recipes)"""

    cache_dir: str = ".cache/recipes"
    proj_kitchen: ProjKitchenSettings = ProjKitchenSettings()
    howtocook: HowToCookSettings = HowToCookSettings()
    nutrition_batch_size: int = 20
    nutrition_max_attempts: int = 2


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
            with open(path, encoding="utf-8") as f:
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
        path = key[len(ENV_PREFIX) :].split(ENV_NESTED_DELIMITER)
        if not all(path):
            continue
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part.lower(), {})
        cursor[path[-1].lower()] = _coerce_env_value(value)
    return result


def _unwrap_annotation(annotation: Any) -> Tuple[Optional[type], bool]:
    """从字段注解里取出嵌套模型; 返回 (模型, 是否是列表)"""
    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            if arg is type(None):
                continue
            return _unwrap_annotation(arg)
        return None, False
    if origin in (list, List):
        args = get_args(annotation)
        return _unwrap_annotation(args[0]) if args else (None, True)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    return None, False


def find_unknown_settings_keys(data: Dict[str, Any], model: type, prefix: str = "") -> List[str]:
    """找出配置里写了、但模型没有对应字段的键

    pydantic 默认会静默忽略不认识的键, 于是 .env 里把 APP__AUTH__DEV_LOGIN 写成
    APP__AUTH__DEV_LOGIN_ENABLED 这种拼写错误不会有任何报错, 只是"配置好像没生效"。
    这里把它们揪出来, 由 load() 统一告警。
    """
    unknown: List[str] = []
    fields = getattr(model, "model_fields", {})
    for key, value in data.items():
        field = fields.get(key)
        if field is None:
            unknown.append(f"{prefix}{key}")
            continue
        nested, is_list = _unwrap_annotation(field.annotation)
        if nested is None:
            continue
        if is_list:
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        unknown.extend(find_unknown_settings_keys(item, nested, prefix=f"{prefix}{key}__"))
        elif isinstance(value, dict):
            unknown.extend(find_unknown_settings_keys(value, nested, prefix=f"{prefix}{key}__"))
    return unknown


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
    wechat: WechatSettings = WechatSettings()
    platforms: PlatformSettings = PlatformSettings()
    scraping: ScrapingSettings = ScrapingSettings()
    recipes: RecipeImportSettings = RecipeImportSettings()

    @classmethod
    def load(cls) -> Settings:
        """按 env > .env > yaml > 默认值 的顺序装配配置"""
        load_dotenv(override=False)
        data = deep_merge(load_yaml_defaults(), env_overrides())
        unknown = find_unknown_settings_keys(data, cls)
        if unknown:
            logger.warning(
                "以下配置项没有对应字段, 已被忽略 (多半是拼写错误, 请注意与文档核对): %s",
                ", ".join(sorted(f"APP__{key.upper()}" for key in unknown)),
            )
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
        self.feishu.verification_token = os.getenv(
            "FEISHU_VERIFICATION_TOKEN", self.feishu.verification_token
        )
        self.feishu.encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", self.feishu.encrypt_key)
        self.feishu.default_chat_id = os.getenv("FEISHU_DEFAULT_CHAT_ID", self.feishu.default_chat_id)

        self.wechat.app_id = os.getenv("WECHAT_APP_ID", self.wechat.app_id)
        self.wechat.app_secret = os.getenv("WECHAT_APP_SECRET", self.wechat.app_secret)

        if not self.auth.jwt_secret:
            self.auth.jwt_secret = os.getenv("JWT_SECRET", "")

    def apply_derived_defaults(self) -> None:
        """补齐依赖其他字段的默认值"""
        if not self.scheduler.db_url:
            self.scheduler.db_url = self.database.url


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings.load()


def reset_settings_cache() -> None:
    """清空配置缓存 (测试用)"""
    get_settings.cache_clear()
