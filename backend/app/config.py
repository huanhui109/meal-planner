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
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "APP__"
ENV_NESTED_DELIMITER = "__"

logger = logging.getLogger(__name__)


class AppSettings(BaseModel):
    """应用基础配置"""

    name: str = "饭决 FAN·DECIDE"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    base_url: str = "http://127.0.0.1:8000"
    cors_origins: List[str] = Field(default_factory=list)


# 数据库连接串的**唯一来源**是环境变量 APP__DATABASE__URL (或 .env),
# yaml 与代码默认值里都不允许出现真实账号密码 —— 它们会被提交进版本库。
# 所以这里只放一个"一眼能认出是没配"的占位值, 并让服务在启动 / 迁移时快速失败。
DATABASE_URL_PLACEHOLDER = (
    "mysql+aiomysql://<user>:<password>@<host>:3306/<database>?charset=utf8mb4"
)

# URL 里出现这些密码, 说明用的是模板默认值而不是真实凭据
PLACEHOLDER_PASSWORDS = (
    "change-me",
    "changeme",
    "your_password",
    "your-password",
    "<password>",
    "{password}",
    "password",
)
DEFAULT_MYSQL_PORT = 3306


def looks_like_placeholder_url(url: str) -> bool:
    """判断连接串是否还是模板占位值

    不能只判 URL 是否等于占位串: 用户很可能照着模板改了账号和库名, 但忘了改密码,
    那种半填充的连接串危害更大 —— 它长得像真的, 会让人以为配好了。
    """
    if not url:
        return True
    lowered = url.lower()
    if "<" in url or "{" in url:
        return True
    return any(token in lowered for token in PLACEHOLDER_PASSWORDS)


class DatabaseSettings(BaseModel):
    """数据库配置 (MySQL 8.0 / utf8mb4)

    url 只有一个来源: 环境变量 APP__DATABASE__URL (或 .env)。
    不在 yaml、不在代码默认值里放凭据, 理由见 DATABASE_URL_PLACEHOLDER。
    """

    url: str = DATABASE_URL_PLACEHOLDER
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


class DecideSettings(BaseModel):
    """「饭决」决策配置 (需求 5 / 6 / 9 / 10)

    决策和周菜单生成是两件事: 周菜单慢而全, 决策快而准。
    这里所有参数都围绕"一次点击、两秒内、给得出口服的理由"。
    """

    # 近 N 天出过的菜不再出现 (硬排除)。这是"近 7 天不重复"的唯一口径。
    no_repeat_days: int = 7
    # 同品类打散: 统计最近 N 餐的品类分布, 出现越多惩罚越大
    category_spread_meals: int = 3
    category_penalty_step: float = 25.0   # 每出现 1 次扣的分
    same_cuisine_penalty: float = 15.0    # 同一菜系连续出现额外扣的分
    # 连续两餐不重样: 上一餐主料重合的惩罚
    main_ingredient_penalty: float = 40.0
    # 软随机: 分差在 random_band 之内的候选一起参与 random.choice, 保证每次略有不同。
    # random_min_choices 是"至少给几个候选参与随机" —— 只取分数最高的 3 个会让用户
    # 连点几次时在固定 3 道菜之间来回横跳, 那正是「饭决」要避免的。
    random_band: float = 5.0
    random_min_choices: int = 3
    # 单次决策最多扫描多少道库内菜谱 (决策要快, 不能全表捞)
    local_candidate_scan: int = 600
    # 打分权重
    # score_cuisine 归零: recipe.cuisine 列目前存的是菜品分类(荤菜/主食/早餐…),
    # 不是菜系, 与用户偏好 cuisines (川湘/粤菜/江浙/日料/家常) 几乎对不上 ——
    # 396 道菜里只有 2 道命中。带着 20 分权重时它在"假装在打分", 还挤占了
    # 库存/天气这些真实权重的空间, 比不打更糟。
    # 本期不做 cuisine 数据清洗。⏳ **恢复条件必须写成可判定形式** (PRD 行动项 12s):
    #   1. recipe.cuisine 已由凌晨 LLM 富集任务标注并回填 —— 看的是 `recipe.enrich_source`
    #      由 'rule' 变成 LLM 的那批行, **不是"任务跑过了"**;
    #   2. 回填后的 cuisine 与用户侧 cuisines 词表(川湘/粤菜/江浙/日料/家常)的
    #      **命中率 >= 60%**。
    #   绑定**效果**而不是绑定**动作**: 只写"回填完成"的话, 跑一次任务回填 10 道也会
    #   被当成达标, 而 20.0 在低命中率下只是把偏差放大 —— 那比现在的 0.0 更糟
    #   (现在是"没在打分", 那时是"按错的分数排序")。
    #
    # ⚠️ 恢复必须**一次改齐 6 处**, 严禁只改主链路 (PRD 行动项 12s):
    #   1. 本行 score_cuisine                                        → 20.0
    #   2. config/default.yaml 的 score_cuisine                       → 20.0
    #   3. shared/decide.ts 的 SCORE.cuisine (离线端同构, 漏改 = 离线/在线结果不一致) → 20.0
    #   4. backend/app/services/replacement_service.py  SCORE_CUISINE → 20.0
    #   5. backend/app/services/generation_service.py    SCORE_CUISINE → 20.0
    #   6. backend/app/services/fridge_menu_service.py   SCORE_CUISINE → **5.0** ⚠️
    #      第 6 处**原值就是 5.0**, 它与前 5 处不同源、不同量级(冰箱菜单的权重结构
    #      不是决策这一套), 别跟着一起写 20.0 —— 那等于把一个从来没存在过的值写回去。
    #      它那一路的权重是 STOCK 60 / COVERAGE_FULL_BONUS 20 / TASTE 10 / BUDGET 10
    #      (fridge_menu_service 的模块级常量), 菜系在里面是**最弱的一档**, 填 20.0
    #      会让它一跃成为第二权重, 直接对抗"按冰箱里有什么重排"的设计意图。
    #      ⚠️ 这一路**没有 random_band**, 所以它的风险是"排序被改写"而不是"抽签带塌"
    #      —— 下面那条 random_band 的警告不要复制给它。
    #
    #   行号会漂(注释一插就变), 定位以**符号名**为准: 4/5/6 都是模块级
    #   `SCORE_CUISINE = 0.0`, 是**硬编码常量**而不是 DecideSettings 字段 —— 改本行
    #   它们不会跟着变。只恢复主链路而漏掉它们, 会出现"决策已经不看菜系、换一换却
    #   还在按菜系排序"的分叉, 而且没人会发现; 本次事故的成因就是这类分叉。
    #
    # 🔴 恢复数值之前**先解决约束**, 不能只把 0.0 改回 20.0:
    #    20.0 > random_band(本类 5.0), 菜系一旦命中就领先整整一个抽签带, 带子会塌成
    #    "只在命中菜系的菜里选"; 换一换那条链路更陡(先截 top3 再切带)。实测过
    #    `+12/-20 → 9 道 / 汤羹 66.2%` 的塌缩, 只恢复数值等于把它原样复现一遍。
    score_cuisine: float = 0.0
    score_spice: float = 15.0
    score_inventory: float = 25.0
    score_weather: float = 18.0
    # 预算贴合: 这一餐落在每餐预算内给满分, 超一点点给部分分, 超太多扣分
    score_budget: float = 15.0
    budget_over_tolerance: float = 1.2
    # 深夜 (late_night) 只保留轻食, 且出餐时间上限
    late_night_max_minutes: int = 20
    # 深夜时段区间 (小时, 含头不含尾, 跨零点)
    late_night_from: int = 22
    late_night_to: int = 5
    # 极简做法卡: 步数下限 / 上限 (需求 10)
    quick_steps_min: int = 3
    quick_steps_max: int = 5
    # 一句话理由最大字数 (需求 6)
    reason_max_chars: int = 20
    # 连续决策多少次之后弹倔强提示 (需求 4)
    stubborn_after: int = 3


class WeatherSettings(BaseModel):
    """天气配置 (需求 9)

    enabled 默认 false: 任何外部天气 API 都可能不可达, 默认关掉保证不引入外部依赖;
    打开后 provider 失败也必须静默降级, 绝不能让"决定吃什么"这件事失败。
    """

    enabled: bool = False
    provider: str = "open-meteo"    # none | open-meteo | heweather
    api_key: str = ""               # 仅 heweather 需要, 由 WEATHER_API_KEY 注入
    city: str = "深圳"
    latitude: float = 22.5431
    longitude: float = 114.0579
    cache_minutes: int = 15
    timeout_seconds: int = 3
    # 温度阈值
    hot_temp_c: float = 32.0
    cold_temp_c: float = 5.0


class SystemOneSettings(BaseModel):
    """System One 决策模型配置 (默认后端: 开源 Laya)

    System One 模型不是聊天模型, 而是一个"判断函数": 喂一段状态文本 + 一组类型化
    问题, 单次前向传播直接输出带校准概率的结构化结果, 只有 choice / score / noul
    三种原语, 不生成自由文本 —— 因此不存在"返回的 JSON 解析失败", 也从架构上
    消除了生成式幻觉。

    它最适合干的正是**规则干不了**的活 —— 把一句口语("今天想吃清淡点的, 别太辣")
    变成结构化意图。反过来, 它不该碰打分排序: 那部分规则已经够快且可离线复现。

    和天气一样, provider 可插拔且默认关闭 —— 决定吃什么的主链路不能因为外部模型
    不可用而失败。

    provider:
      laya     默认。Apache-2.0 开源(convaiinnovations/laya), 421M, 本地推理,
               无需 Key、无网络调用、可私有化部署。Jev 的开源平替, 接口对齐,
               延迟更低、概率校准更好(ECE 0.081 vs Jev 0.246)。
      jev      官方 TypeSafe API (https://api.typesafe.ai)。需要 TYPESAFE_API_KEY,
               且账号必须通过官方白名单开白, 无自助注册入口。
      adapter  官方开源 system-one-adapter, 背后接 OpenAI 兼容端点(LM Studio)。
               机器上装不了 torch 时的退路。
      rule     纯规则兜底, 零外部依赖, 永远可用。
    """

    enabled: bool = False
    provider: str = "laya"  # laya | jev | adapter | rule
    timeout_seconds: float = 1.5  # 只对 jev / adapter 生效; laya 是本地同步推理
    cache_seconds: int = 300
    # 低于此置信度的判断不采纳。System One 的 confidence 是校准过的,
    # 这正是它比"让 LLM 自己说有多大把握"可靠的地方。
    # 0.90 同样是语料拟合出来的: 菜系 Choice 的命中率随阈值单调上升
    # (0.55→23% / 0.80→33% / 0.90→67%), 即零样本下它只有极少数高置信判断可信,
    # 取 0.90 等于"只在模型极其确定时才认它的菜系"。
    min_confidence: float = 0.90

    # Noul 返回的是"该陈述为真"的概率, 这两个阈值把它折叠成三态:
    # >= noul_accept 判为真 / <= noul_reject 判为假 / 中间地带**不采纳**(交给规则)。
    #
    # 0.91 / 0.20 由 scripts/system_one_calibrate.py 在 data/utterance_corpus.json
    # (106 条中文语料 × 6 个问题) 上拟合, 代价非对称: 凭空加一条用户没说的约束罚 2 分,
    # 漏掉一条罚 1 分。同批数据上 F1: 纯规则 0.81 / 纯模型 0.47 / 模型+规则逐维度融合 0.86。
    #
    # ⚠ 换权重、换问题措辞、换用户群之后必须重跑拟合再改这两个数。Laya 零样本在中文上
    # 的绝对精度就是这样(菜系 Choice 命中率只有 67%), 想再往上只能微调权重。
    noul_accept: float = 0.91
    noul_reject: float = 0.20

    # ---- Laya 专用 ----
    laya_model: str = "convaiinnovations/laya"
    # english | multilingual | typed-decisions | auto
    # 中文场景必须用 multilingual(或 auto 让 Router 按语种自动分发);
    # english 权重遇到非拉丁字符会静默失效 —— 不会报错, 只是判得差。
    laya_checkpoint: str = "multilingual"
    laya_device: str = ""  # 留空自动选择(macOS 会用 mps)
    laya_max_loaded: int = 2  # checkpoint=auto 时 Router 最多常驻几个权重

    # ---- Jev 专用 ----
    api_key: str = ""  # 仅由 TYPESAFE_API_KEY 注入
    model: str = "jev-latest"
    base_url: str = ""  # 留空用 SDK 默认 https://api.typesafe.ai

    # ---- adapter 专用 ----
    adapter_provider: str = "openai"
    adapter_base_url: str = "http://127.0.0.1:1234/v1"
    adapter_model: str = "zai-org/glm-4.6v-flash"
    adapter_api_key: str = ""  # 本地端点一般不需要, 留空
    # 关掉后适配器改用"提示词要求返回 JSON"的模式。实测 LM Studio 在关闭时会拒绝
    # 请求(response_format 的 type 为 null), 所以默认保持开启。
    adapter_structured_outputs: bool = True

    @property
    def usable(self) -> bool:
        """开启且所选 provider 具备调用条件。rule 永远可用, 因为它不打电话。"""
        if not self.enabled:
            return False
        if self.provider == "rule":
            return True
        if self.provider == "laya":
            return bool(self.laya_model)
        if self.provider == "jev":
            return bool(self.api_key)
        if self.provider == "adapter":
            return bool(self.adapter_base_url and self.adapter_model)
        return False


class DishEnrichSettings(BaseModel):
    """菜品富集配置 —— 兜底大模型的新岗位

    定位说明 (这条最容易搞混, 写清楚):
        Laya(开源 System One) 负责**实时决策**: 一次前向传播把口语诉求变成结构化意图,
        必须在 2s 内返回, 所以只能干"判断"这种轻活。
        兜底大模型(FallbackChain) 负责**离线生产**: 定时补菜品、写做法、补缺失字段。
        它慢、要花钱、输出还不稳, 但能干"创造内容"这种重活 —— 而这活绝不能放进决策链路。

    所以这两者不是主备关系, 是**分工关系**。本配置只管后者。

    enabled 默认关闭: 和天气/System One 一个道理 —— 决定吃什么的主链路不能因为
    外部模型不可用而失败。富集是加分项, 跑挂了最多是字段还缺着。
    """

    enabled: bool = False
    # 单次最多处理几道菜。LLM 是按道收费的, 这个值就是账单上限。
    batch_limit: int = 20
    # 一次最多生成几道新菜。宁可少: 新菜品要进决策池, 质量比数量重要得多。
    expand_limit: int = 5
    # 温度压低: 富集的产出是数据不是文案, 要稳定不要灵光
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout_seconds: float = 60.0
    # 人工校对过(enrich_source=manual)的菜一律跳过, 不许 LLM 覆盖
    respect_manual: bool = True
    # 补新菜时的约束: 只在这些品类里补, 空表示不限
    expand_categories: List[str] = Field(default_factory=list)


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
    # 凌晨跑: LLM 调用不占白天决策的响应时间, 且此时段失败重试也不打扰用户
    recipe_enrich: str = "03:30"


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

    #: V3.0 脚手架总开关: 默认关闭, 调度器注册了 daily_scrape_products 但不会真实采集
    enabled: bool = False
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
    decide: DecideSettings = DecideSettings()
    weather: WeatherSettings = WeatherSettings()
    system_one: SystemOneSettings = SystemOneSettings()
    dish_enrich: DishEnrichSettings = DishEnrichSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    llm: LLMSettings = LLMSettings()
    feishu: FeishuSettings = FeishuSettings()
    wechat: WechatSettings = WechatSettings()
    platforms: PlatformSettings = PlatformSettings()
    scraping: ScrapingSettings = ScrapingSettings()
    recipes: RecipeImportSettings = RecipeImportSettings()

    # V1.2.0 R-16: 首页灰度版本。服务端下发这个值, 前端据它渲染 v1.1 / v1.2 两套布局。
    #
    # 为什么必须是服务端下发而不是客户端自己判断: 同一个 app 版本的用户可能落在两个
    # 灰度组(app_version 现在 100% 是 "unknown", 根本切不动), 只有服务端的值能把
    # "改版是好是坏"切开 —— 没有它, 埋点和首页即使同版上线也说不清 DCR 的变化归因。
    #
    # 为什么默认是 None 而不是 'v1.2':
    #     **后端不许替前端兜底**。服务端没配就是没灰度、用户不知道自己分在哪组,
    #     此时必须返回 null; 若替它填一个 'v1.2', 这批"不知道自己在哪组"的行会被
    #     算进某一组, 灰度结论直接失效。'v1.2' 的兜底是**前端**的事(layout-version.ts)。
    #
    # 改灰度不用改代码: 设环境变量 APP__LAYOUT_VERSION=v1.1(或改 config/default.yaml),
    # 重启即生效 —— 这就是 R-16 ③ 要的"可不发版把任意用户切回 v1.1"。
    layout_version: str | None = None

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

        if not self.weather.api_key:
            self.weather.api_key = os.getenv("WEATHER_API_KEY", "")

        # Jev 官方 Key。注意: 光有 Key 不够, 账号还得通过 TypeSafe 白名单开白。
        # 默认走开源 Laya, 所以这一项留空完全不影响使用。
        if not self.system_one.api_key:
            self.system_one.api_key = os.getenv("TYPESAFE_API_KEY", "")

        if not self.auth.jwt_secret:
            self.auth.jwt_secret = os.getenv("JWT_SECRET", "")

    def apply_derived_defaults(self) -> None:
        """补齐依赖其他字段的默认值"""
        if not self.scheduler.db_url:
            self.scheduler.db_url = self.database.url

    # ---------------------------------------------------------------- 启动校验

    def describe_database(self) -> str:
        """给日志/报错用的脱敏地址。任何时候都不要把完整 URL 写进日志,
        连接串里带密码, 日志一旦外泄就是凭据泄露。"""
        try:
            parsed = urlparse(self.database.url)
        except ValueError:
            return "<无法解析的连接串>"
        if not parsed.hostname:
            return "<未配置连接串>"
        return (
            f"{parsed.scheme}://{parsed.username or '?'}:***@"
            f"{parsed.hostname}:{parsed.port or DEFAULT_MYSQL_PORT}"
            f"{parsed.path or ''}"
        )

    def validate_for_runtime(self, *, require_db: bool = True) -> None:
        """服务启动 / 数据库迁移前的快速失败校验

        只在真正要连库的入口调用 (main.py 的 lifespan 与 alembic/env.py),
        不放在 Settings.load() 里 —— 那样纯逻辑单测也会被迫配一个数据库,
        反而会逼着人在测试里塞真凭据。
        """
        if not require_db:
            return

        url = self.database.url
        if looks_like_placeholder_url(url):
            raise RuntimeError(
                "数据库连接串还是模板占位值, 没有配置真实凭据。\n"
                "  请在 .env 里设置 APP__DATABASE__URL, 或直接导出环境变量:\n"
                '    export APP__DATABASE__URL="mysql+aiomysql://<用户>:<密码>@127.0.0.1:3306/meal_planner?charset=utf8mb4"\n'
                "  模板见 .env.example; 本地一键建库建账号: bash scripts/setup_local.sh"
            )

        parsed = urlparse(url)
        scheme = parsed.scheme
        if not scheme.startswith("mysql"):
            # SQLite 只在脚本离线冒烟时用, 服务本身只认 MySQL
            raise RuntimeError(
                f"数据库连接串的方言是 {scheme!r}, 服务只支持 MySQL (mysql+aiomysql / mysql+asyncmy)。\n"
                f"  当前地址: {self.describe_database()}"
            )
        if parsed.port and parsed.port != DEFAULT_MYSQL_PORT:
            logger.warning(
                "数据库端口是 %s, 不是默认的 %s —— 如果这是历史遗留的专用实例请忽略本条, "
                "否则多半是配错了: %s",
                parsed.port,
                DEFAULT_MYSQL_PORT,
                self.describe_database(),
            )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings.load()


def reset_settings_cache() -> None:
    """清空配置缓存 (测试用)"""
    get_settings.cache_clear()


def current_layout_version() -> str | None:
    """当前首页灰度版本 —— 没配置就是 None

    放在配置模块而不是某个 API 模块里: /api/decide 和 /api/today 都要下发它,
    放在 decide 那边会让 today 反向依赖一个跟它不相干的接口模块。

    ⚠️ 绝不能兜底成 'v1.2'。服务端不知道用户被分在哪组时必须返回 null:
    '不知道' 和 '在 v1.2 组' 是两回事, 混成一个值会把灰度结论算歪 —— 那批用户会
    被当成 v1.2 的样本。前端拿到 null 时自己退回默认值, 那是它该做的事。
    """
    value = get_settings().layout_version
    if value is None:
        return None
    cleaned = value.strip()
    # 配了 key 但值是空串等于没配 —— yaml 里手抖留空是常态
    return cleaned or None
