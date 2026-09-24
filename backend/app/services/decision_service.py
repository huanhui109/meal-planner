"""饭决决策引擎 (需求 5 / 6 / 9 / 10)

一句话职责: 给定一个人 + 一个时刻 + 一段历史, 输出一道菜 + 一句理由。

与周菜单生成 (generation_service) 的本质区别:
    周菜单是"规划", 慢而全, 允许 1-2 分钟, 追求营养与预算达标;
    决策是"回答", 必须 2 秒内, 追求 **这一次** 不重复、不腻、说得出口服。
所以这里不复用 generation_service 的任何打分 —— 那边的权重(热量50/库存30/菜系20)
是为"排满一周"设计的, 搬到单餐决策上会得到一堆热量刚好但不合时宜的菜。

三条硬规则 (需求 5) 在这里是**硬**的:
    近 7 天不重复 / 同品类打散 / 连续两餐不重样
现有 diversity_service 只对周菜单做"事后劝阻", LLM 路径下重复菜会真的落库;
这里反过来 —— 先过滤再挑, 宁可放宽到"可选项不多"也不出重复菜。
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.data.local_pool import LOCAL_DISHES
from app.models.allergy_restriction import AllergyRestriction
from app.models.budget import Budget
from app.models.decision import DecisionLog, DecisionSource, MealSlot
from app.models.diet_preference import DietPreference
from app.models.fridge_inventory import FridgeInventory
from app.models.household import Household
from app.models.ingredient import Ingredient
from app.models.menu import Menu, MenuItem
from app.models.recipe import Recipe
from app.schemas.serializers import json_list
from app.services.dish_rules import dish_only
from app.services.intent_service import MealIntent, MealIntentService
from app.services.pricing_service import PricedRow, PricingService
from app.services.reason_service import ReasonContext, ReasonService
from app.services.weather_service import WeatherContext, WeatherService

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# 餐次 → 当天大致钟点。用来给同一天的多餐排出先后,
# 这样「上一餐」才是真正上一餐, 而不是当天最早那一餐。
_MEAL_HOURS = {"breakfast": 8, "lunch": 12, "dinner": 18, "late_night": 22}

# 菜名归一化的别名表。
# 「近 7 天不重复」靠字符串匹配, "番茄炒蛋" 和 "西红柿炒鸡蛋" 必须判成同一道菜,
# 否则用户会明显感觉到"昨天刚吃过怎么又来"。这张表是人工维护的,
# 遇到漏网的再补 —— 比引入分词/相似度划算得多。
ALIAS_PAIRS = {
    "西红柿": "番茄",
    "马铃薯": "土豆",
    "洋芋": "土豆",
    "包菜": "卷心菜",
    "甘蓝": "卷心菜",
    # 蛋 vs 鸡蛋: 「番茄炒蛋」和「西红柿炒鸡蛋」必须归一到同一个 key
    "鸡蛋": "蛋",
    "鸡旦": "蛋",
    "鸭蛋": "蛋",
    "大葱": "葱",
    "小葱": "葱",
}

# column String(36) 的列宽, 与 events.py 的 MAX_SESSION_ID_LEN 保持一致 ——
# 一边的会话 ID 被截断了, join 就静默丢一半。
_SESSION_ID_LEN = 36

# 夜宵额外放行的品类。
#
# 为什么单独开白名单, 而不是把蛋炒饭标成 is_light=1:
#   is_light 白天还要服务"想吃清淡点"(MealIntent.require_light)。
#   把蛋炒饭标成轻食, 用户白天说"来点清淡的"就会拿到蛋炒饭 —— 修一个问题制造另一个问题。
#   所以这条白名单只在深夜分支生效, 绝不污染 is_light 字段。
#
# 为什么是主食/面食: 实测 is_dish=1 ∩ is_light=1 ∩ <=20min 只有 16 道,
# 且这 16 道里主食 0 / 面食 0 / 汤羹 0 —— 深夜"想吃碗面"完全无解;
# 而全库 cook_minutes<=20 的主食/面食有 29 道, 且无一被标为轻食。
# 加白名单后夜宵池 16 -> 45 (<=15min 口径下 16 -> 34)。
LATE_NIGHT_EXTRA_CATEGORIES = ("主食", "面食")

# 抽签池水位线 (R-10): 少于这么多道就往下一档放宽。
# 8 不是拍脑袋: 决策最终是在 random_band 分差带里随机抽一道, 池子太小用户连点几次
# 「换一个」会在同样的两三道之间来回横跳, 反而加深"这个 App 就这几道菜"的印象。
# 依据 random_min_choices(3) + random_band(5) 的量级取 8。
POOL_MIN = 8

# 放宽阶梯的最高档。4 = 连「近 7 天不重复」都松了, 这是地板, 不能再往下。
MAX_RELAX_LEVEL = 4

# 每档的名字 —— 提醒: 光看索引 2 / 4 转眼就记不得是谁了。
# SQL / 埋点 / decision_metrics 的阈值一律引用这两个名字, 不要在别处写数字:
# J3 的门槛已经漂过三次 (旧 relaxed=true → 6 档时的 3 → 5 档时的 2)。
RELAX_LEVEL_CATEGORY_SPREAD = 2   # 松到这一档 = 同品类打散不再扣分
RELAX_LEVEL_NO_REPEAT = 4         # 松到这一档 = 「近 7 天不重复」也失效 (最后的安全线)

# meal_slots 软惩罚 (R-11)。 meal_slots 覆盖率只有两成多, 所以是"加分"不是"能不能进池"。
#
# ⚠️ 幅度为什么这么小 —— 在 random_band 抽签机制下, 任何「命中 / 不命中」型二元打分
# 的幅度必须 <= random_band (当前 5.0)。超过它, band 里只会剩下一侧的菜:
#   减分侧表现为「准硬过滤」(被罚菜全部出局),
#   加分侧表现为「band 独占」(受加分菜抬高最优分、把其他人挤出带)。
# 这是同一枚硬币的两面。改这类幅度前, 先算 幅度 vs random_band。
#
# 实测 (晚饭档, 500 次采样, 真库 342 道): +12/-20 会让汤羹占 65-77%、主食面食掉到
# 0-4%、32 道候选只剩 8-9 道能抽到; +3/0 回落到汤羹 7.4%、主食面食 21.5%、32 道,
# 与自然占比基本一致 —— 即"影响排序, 但不替用户做排除"。
#
# ⚠️ 这条约束是**绑定 random_band 的**: 谁改了 default.yaml 的 random_band, 必须回头
# 重算这里的幅度(保持 < random_band)。这就是 score_cuisine=20 那类"静默失效"的教训:
# 常量看起来还在, 但它引用的那把尺子已经换了。
MEAL_SLOT_MATCH_BONUS = 3.0
# 减分置 0 而不是取个小负数: 覆盖率这么低, 减分命中与否几乎取决于标注有没有做,
# 拿一群库的"标注运气"去压另一群, 不如干脆不罚。
MEAL_SLOT_MISMATCH_PENALTY = 0.0

# ---- 早餐代理补偿 ----
#
# meal_slots 覆盖率只有两成多, 早餐档不能只靠标注。但也不能照旧口径给 12.0 / 8.0:
# 那两个数是 random_band(5.0) 的 2.4 倍和 1.6 倍, 两项全中叠到 20 分 ——
# 早餐档的抽签带会被这两笔直接切成「主食快手 / 其它」两半, 早餐从此只有那几道。
#
# 改由两个**代理信号**补位: 品类(主食/面食) 与出餐时间(<=15min)。
# 幅度 3.0 + 1.5 = 4.5 < 5.0, 留 0.5 余量。1.5 不是 2.0 就是为了留这个余量。
#
# ⚠️ 与餐次贴合**取最大值, 不叠加** (见 _score): 两者是同一信号
# ("这道菜适不适合早餐")的两个来源, 单独叠加会让三项全中的菜拿到 7.5 > band。
#   2026-09-23 实测过叠加(「叠加 7.5」方案)并被回退: 4 场景 × 补标前后 8 格挂 2 格
#   (见 _score 里的说明与 band_regression.py 的早餐结果判红)。**别再试一次同样的
#   改动而不先看那 8 格** —— 幅度判据判不出分布, 只有结果判据判得出。
# ⚠️ 也不能改成"标了就跳过补偿": 那样标了 breakfast 只拿 3.0、没标的主/面拿 4.5,
#    代理分反而高于显式标注分 —— 标得越全分越低, 没人愿意补标注。
BREAKFAST_CATEGORY_BONUS = 3.0
BREAKFAST_QUICK_BONUS = 1.5

# ---- 软偏好包统一封顶 ----
#
# 单项各自 <= random_band 是**必要非充分**: 同一餐次下会同时命中的几笔叠起来照样穿。
#   例: 早餐补偿 4.5 + 库存命中 4.0 = 8.5 > 5.0 —— 单项都合规, 合起来已经能切带。
# 所以把软偏好类的加成合成一个包, 包整体再封一次顶。
#
# 为什么是 4.0 而不是 random_band 本身 (5.0):
#   包取满就等于"所有人都一样 ≈ 谁都没进包", 而更糟的是它会把选择变成准硬过滤 ——
#   封顶 5.0 = 随机 band 时零余量: 未命中那组要 base 分落在 0 分以内才进得来。
#   留 1.0 余量, 与 INVENTORY_SCORE_CAP 用同一条规矩(两条封顶一条规矩)。
# ⚠️ 改这个值之前先看一眼包内成员的典型合计: 取到满值不是目标, 留余量才是。
#
# 4.0 这个数的完整理由 (2026-09-23 team-lead 采纳) —— 别只看见 "= 4.0", 要看见它能用到哪:
#   1. 余量: 4.0 < random_band 5.0, 留 1.0。取成 band 本身就是零余量, 包会退化成准硬过滤。
#   2. prefer_fridge **不在本包预算内**: 它已从包里移出, 改成乘在库存命中数上
#      (PREFER_FRIDGE_MULTIPLIER, 见本文件下方 —— 它是系数不是加分项, 不占包预算)。
#      在此之前它是一笔对每道菜都成立的 +6.0 全量加分, 会先把预算烧光;
#      移走之后包内剩下的几笔才真的有空间分化。
#   3. 包内现在剩下: max(餐次贴合, 早餐补偿) + 库存命中 + intent.bonus() —— 见 _score()。
#      ⚠️ 注意第 3 条与"包内只剩两项"的说法不同: 餐次贴合/早餐补偿**仍在包内**
#      (2026-09-23 试过把它们移到包外叠加的「方案 A」, 因早餐档 8 格挂 2 格被回退,
#      见 _score() 里那段)。所以库存命中仍然要和它们抢同一份预算:
#      早餐档「主食/面食 ∩ <=15min」的菜, max(...) 单笔就到 4.5 > 4.0 ——
#      这批菜的软包恒等于封顶值, 库存/口语诉求在它们身上**没有边际作用**。
#      这不是 4.0 的错(降封顶只会更早饱和), 但它是下一版要处理的真问题:
#      要么让早餐补偿与库存分列两个包, 要么把封顶改成"分项封顶再相加"。
#
# 包内成员: 餐次贴合 / 早餐补偿(两者取 max 后进包) / 库存命中 / 口语诉求 intent.bonus()
#
# ⚠️ 是"不得超过"的上限, 不是"建议取到"的值 —— 取满就等于用软偏好替用户做排除。
# ⚠️ 成员增减要同步 shared/decide.ts。离线端没有 intent(口语解析在服务端),
#    离线那侧的包少这一项, 是唯一一处有意的差异, 别当漂移去"修"。
# ⚠️ `_weather_score` 不进包: 它当前不产生分数(weather.condition 为 None 时整体返回 0),
#    且幅度是 score_weather=18.0 —— 是 random_band 的 3.6 倍。恢复启用前必须先把
#    幅度压到 <= random_band, 否则一启用就把抽签带切成"雨天菜/非雨天菜"。
SOFT_PREFERENCE_CAP = 4.0

# ---- 葱 / 姜 / 蒜: 2026-09-23 判定「不做」, 整件排 V1.3 ----
#
# 问题仍在, 只是不在这一版修: 它们几乎出现在每一道中式菜里, 用户只要往冰箱里录了
# 葱姜蒜, 大批菜凭空拿到库存加分 —— 含葱姜蒜的冰箱下 FULL=2 会提前饱和
# (11 样时 52.3% 的菜拿满分), 库存信号区分度归零。这不是边缘场景。
#
# 为什么不做 (team-lead 5a 判据: 排序修复不得让用户可见文案的触发率变化超过 ±5pp):
#   剔除范围一变, `_needed_ingredients` 这个**同时是分子(hits)和分母(len)**的
#   函数就跟着变, 连带改动「交给外卖吧」(ratio < 0.3) 与雨天门槛的触发率。
#   实测(真库 342 道, N=300, seed=20260923, dinner):
#       S1 小冰箱(含葱姜蒜)  79.7% -> 93.3%   +13.7pp
#       S2 中冰箱(含葱姜蒜)  65.0% -> 75.7%   +10.7pp
#       S3 大冰箱(含葱姜蒜)  61.7% -> 76.3%   +14.7pp
#       S2' 中冰箱(不含)     83.3% -> 75.7%    -7.7pp  (分母变短, 方向都不唯一)
#   三个方案(A 精确串 / B 扩 _STAPLES / C 子串+蔬菜白名单)全部超 ±5pp ——
#   不是"改得不够巧", 而是这两个消费点共用一套 need, 动一个必动另一个。
#
# V1.3 的正确修法: 把 need 拆成两份 —— 排序用去调味料的 need, 文案/雨天继续用
#   现有 need, 触发率一行不动。那是"文案口径"的产品决策, 不是排序决策, 本版不做。
#
# ⚠️ 顺带一条基线异常(与本次改动无关, 但值得单独开单): 改**前**的触发率就已经是
#    61.7%~97.0% —— 雨天里这句"次级出口"文案几乎是默认文案, 不是例外出口。

# ---- R-09: 库存打分归一化 ----
#
# 旧口径 `score_inventory * (hits / len(need))` 有两个毛病, 而且是同一个根:
#   1. 分母是**这道菜自己的食材数**, 于是 2 样食材的菜只要录中 1 样就满分(1/2=50% 拿满),
#      6 样食材的菜录中 3 样才 50% —— 奖励的是「食材少的简单菜」, 不是「你家有的菜」;
#   2. 幅度是 score_inventory=25.0, 是 random_band(5.0) 的 5 倍 —— 录了食材之后
#      抽签带从 60 道塌到 3 道 (data-analyst 基线实测), 用户反而更看不到菜。
#
# 修法 (方案 A): 拆成两个语义, 各归各位
#   `_inventory_ratio` —— 一行不改。它还供 `_weather_score`(雨天 0.3/0.1 两档)和
#                          「交给外卖吧」文案用, 这两个消费点的触发率必须前后完全一致。
#   `_inventory_hits`  —— 新增, 只服务排序: 命中数 / 固定分母, 与这道菜有多少食材无关。
#
# 为什么是 2 (data-analyst A22 定标, 真库 342 道实测, 全程只读零写入):
#   FULL=3 (初值) ✗: 真实小冰箱的 hits 分布是 0:234 / 1:99 / 2:8 / 3:1 —— 只有 1 道菜
#                    (0.3%) 能拿满, 主流只拿到 1.67/5 = 33%, R-09 等于没接线;
#   FULL=1 ✗:       完全二元, 大冰箱(S3 8样)下 74.6% 的菜同分, 库存信号区分度归零;
#   FULL=2 ✓:       小冰箱主流拿 2.5/5 (半档), 保住"1 样 < 2 样"的区分,
#                   三个库存集 natural_band 54 / 70 / 95 全健康。
# 改这个值等于重拍 R-09 的基线: 它不是"手感", 命中分布变了就要重新定标。
INVENTORY_HITS_FULL = 2
# 库存家族(命中加分 + 临期加分)合起来的幅度硬上限。
# 为什么是"合起来": 两笔都是库存派生量, 分开各封 5 分叠起来就是 10, 照样能切带。
#
# 为什么是 4.0 而不是 random_band 本身 (5.0):
#   档位落成 0 / 2.0 / 4.0 (见 _inventory_score), 跨度 4.0, 距 band 留 1.0 余量。
#   R-14 指出默认场景下 `_score()` 实际只有 score_spice 一个维度在工作 ——
#   R-09 是**唯一**能让打分真正多维的入口, 压到 3.0 会让它掉到噪声量级。
#   外层还有 SOFT_PREFERENCE_CAP 兜着整包, 单项留 1.0 余量够。
# ⚠️ 与 meal_slots 同一个约束: 谁改 random_band, 必须回头重算这个上限。
INVENTORY_SCORE_CAP = 4.0

# prefer_fridge 不进软偏好包, 而是放大库存命中数 —— 它表达的是"更想用冰箱食材",
# 不是"给所有菜加一个常数"。放大后仍由 INVENTORY_SCORE_CAP + SOFT_PREFERENCE_CAP 兜住。
# ⚠️ 通用教训: 把一个全量加分放进一个有预算上限的包, 等于用常数把预算烧光。
#    以后往包里加新项, 第一件事是先问它是不是全量的。
PREFER_FRIDGE_MULTIPLIER = 1.5

_PUNCT = re.compile(r"[\s·・,，、\-—_()（）【】\[\]]+")


def normalize_dish_name(name: str) -> str:
    """归一化菜名: 去标点空白 + 别名收敛"""
    text = _PUNCT.sub("", (name or "").strip())
    for src, dst in ALIAS_PAIRS.items():
        text = text.replace(src, dst)
    return text


@dataclass
class Candidate:
    """候选菜 —— 统一了 Recipe ORM 与本地池 dict 两套来源

    为什么要有这一层: 库里有菜谱时从库里选(能算库存命中),
    库空时(新用户/演示环境)从本地池选。两条路的打分必须完全一样,
    所以先把它们抹平成一个结构。
    """

    id: Optional[int]
    name: str
    cuisine: str
    category: str
    main: str
    minutes: int
    calories: int
    difficulty: int
    spice: int
    light: bool
    cover: str
    tags: List[str]
    flavors: List[str]
    ingredients: List[str]
    steps: List[str]
    from_pool: bool = False
    # 适合餐次 JSON 数组 (meal_slots); 空 = 不限制, 不是"哪顿都不合适"
    meal_slots: List[str] = field(default_factory=list)
    # 所需厨具 JSON 数组 (tools): pot/steamer/oven/air_fryer; 空 = 没有特殊要求。
    # 只用于结果卡展示, 不参与过滤/打分 —— 用户是看到"需烤箱"才想起自己没有烤箱的。
    tools: List[str] = field(default_factory=list)
    # 按食材参考单价估出来的这一餐成本(元); 估不出价时为 None, 不参与预算打分
    cost: Optional[float] = None

    @property
    def haystack(self) -> str:
        """过敏/忌口匹配用的文本: 菜名 + 所有食材名"""
        return " ".join([self.name] + self.ingredients)


@dataclass
class RecentHistory:
    """近 N 天的饮食事实。决策的全部"记忆"都在这。"""

    names: set = field(default_factory=set)              # 近 7 天归一化菜名
    category_counts: Dict[str, int] = field(default_factory=dict)
    cuisine_counts: Dict[str, int] = field(default_factory=dict)
    last_main: Optional[str] = None                      # 上一餐主料
    last_cuisine: Optional[str] = None
    last_category: Optional[str] = None
    dish_last_seen: Dict[str, date] = field(default_factory=dict)
    days_since_spicy: Optional[int] = None


class PickResult(NamedTuple):
    """一次筛选的结果

    relaxed_level / candidate_count / band_size 都要落库: 只有 relaxed_level 的话,
    「有多少次决策放宽了」这个数字会随着"什么时候算放宽"的口径变化而变化, 无法前后对比;
    带上放宽**前**的池子大小, 旧口径随时能重算出来。

    band_size 是用户真正在其中抽签的那几道 —— candidate_count 会高估选择空间
    (通过了过滤不等于真的进了抽签带), 两个值分开才看得出"用户在几道菜里选"。

    ⚠️ band_size 有下限、不单调: 真带不足 random_min_choices 时会按分数补齐到它,
    于是 `band_size >= random_min_choices` 是**恒真**的 —— 拿它当判据永远测不出塌缩。
    要看"抽签带是不是真塌了"请用 natural_band_size (只数 score >= best - random_band,
    不含补齐)。两个数一起看还能反查出"是不是被 padding 顶住的"。
    """

    candidate: Optional[Candidate]
    relaxed_level: int
    candidate_count: int
    band_size: int = 0
    natural_band_size: int = 0


def _clean_session_id(value: Optional[str]) -> Optional[str]:
    """会话 ID 归一化: 去空白 + 截断到列宽

    口径与 app/api/events.py 的 _normalize_session_id 一致: 不做 UUID 校验 ——
    埋点宁可存下一个格式不对的值让人能查到"谁传错了", 也不要静默丢掉整条链路。
    """
    return (value or "").strip()[:_SESSION_ID_LEN] or None


# 决策上下文里那些"当时到底按什么过滤的"。放进 decision_log.filters_snapshot,
# 让"为什么那一刻没菜可选"事后能复现 —— 只看代码版本是猜不出来的。
#
# ⚠️ 刻意不存忌口/过敏的**原词**: 那是用户的健康隐私, 进了快照就等于进了每一个
# 能查这张表的地方。计数足够回答"是不是忌口把池子卡死了", 回答不了才值得单独取数。
def _filters_snapshot(
    profile: Profile,
    slot: str,
    excluded: set,
    intent: Optional[MealIntent],
    relaxed_level: int,
    cook_cap: Optional[int],
    pool_topped_up: bool = False,
) -> Dict[str, Any]:
    return {
        "meal_slot": slot,
        # 候选池不足 20 道、用本地池补齐过 —— 补齐那批菜**零过滤**(见
        # load_candidates), 包括忌口/过敏/时间上限。这个标记让"那一刻用户的忌口
        # 到底生效了没有"事后可查: 现在没有任何地方知道补齐路径触发得多频繁。
        "pool_topped_up": pool_topped_up,
        # 放宽之后实际生效的时间上限; None = 这一届放宽时把上限摘了
        "cook_cap": cook_cap,
        "late_night_max_minutes": get_settings().decide.late_night_max_minutes
        if slot == MealSlot.LATE_NIGHT
        else None,
        "avoid_count": len(profile.avoid),
        "allergen_count": len(profile.allergens),
        "excluded_count": len(excluded),
        "has_intent": intent is not None,
        "meal_budget": profile.meal_budget,
        "relaxed_level": relaxed_level,
    }


@dataclass
class Profile:
    """决策所需的压缩档案"""

    cuisines: List[str] = field(default_factory=list)
    spice_level: int = 2
    avoid: List[str] = field(default_factory=list)
    allergens: List[str] = field(default_factory=list)
    scene_tags: List[str] = field(default_factory=list)
    cook_cap: int = 60          # 出餐时间上限(分钟)
    has_profile: bool = False
    # 这一餐的预算上限(元): 日预算按当日餐次均摊; 用户没设过预算时为 None
    meal_budget: Optional[float] = None


class DecisionService:
    # 本次决策的候选池是否动用过本地池补齐 —— 只做观测, 不影响任何打分/过滤。
    # 默认 False: 走过的路径没调用 load_candidates 时, 按"没补齐"记, 而不是炸。
    _pool_topped_up: bool = False

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings().decide
        self.reason_service = ReasonService()
        self.weather_service = WeatherService()

    # ------------------------------------------------------------------ 主流程

    async def decide(
        self,
        user_id: int,
        meal_slot: Optional[str] = None,
        exclude: Optional[Sequence[str]] = None,
        now: Optional[datetime] = None,
        utterance: Optional[str] = None,
        session_id: Optional[str] = None,
        reroll_index: int = 0,
    ) -> Dict[str, Any]:
        """输出一次决策。返回的 dict 直接就是 DecisionResult 的结构。

        utterance 是用户的一句口语诉求(如"今天想吃清淡点的, 别太辣")。给了才会
        去解析, 不给就完全不碰 System One 模型 —— 主链路的默认形态仍然是纯规则的。
        解析结果只做减法过滤和小幅加分, 不参与打分权重的重构。

        session_id / reroll_index 来自请求, 只是被落进 decision_log 的两列 ——
        它们回答的是"这个会话里发生了什么"和"用户点了几遍换一个才拿到这个结果",
        决策引擎本身不用它们也算得出菜。
        """
        moment = now or datetime.now(CST)
        slot = self._resolve_slot(meal_slot, moment)
        today = moment.date()

        profile = await self.load_profile(user_id)
        history = await self.load_recent_history(user_id, today)
        weather = await self.weather_service.get()
        inventory, expiring = await self.load_inventory(user_id, today)

        candidates = await self.load_candidates()
        excluded = {normalize_dish_name(x) for x in (exclude or [])}

        intent = await self._understand(utterance, slot=slot, inventory=inventory)
        if intent is not None and intent.has_constraints:
            narrowed = [c for c in candidates if intent.allows(c)]
            if narrowed:
                candidates = narrowed
            else:
                # 诉求把候选砍空了(比如"想喝汤"但池里一道汤都没有)。这时照常出菜,
                # 而不是返回空 —— 用户要的是"今天吃什么", 不是"没有符合条件的菜"。
                logger.info("口语诉求过滤后无候选, 已忽略: %r", utterance)
                intent = None

        outcome = self._pick(
            candidates=candidates,
            profile=profile,
            history=history,
            weather=weather,
            inventory=inventory,
            expiring=expiring,
            slot=slot,
            excluded=excluded,
            today=today,
            intent=intent,
        )
        picked = outcome.candidate
        # relaxed 是给用户的"我没完全守规矩"的诚实口径, 一旦放宽过就算
        relaxed = outcome.relaxed_level > 0

        if picked is None:
            # 理论上到不了这里: 本地池兜底保证候选非空。真到了就明确报错, 不要静默给个空的。
            logger.error("决策候选用尽: user_id=%s slot=%s", user_id, slot)
            raise RuntimeError("没有可推荐的菜，请先在设置里放宽忌口或时间预算")

        reason = self._build_reason(
            picked=picked,
            history=history,
            weather=weather,
            expiring=expiring,
            inventory=inventory,
            slot=slot,
            relaxed=relaxed,
            today=today,
        )

        result = self._build_result(
            picked=picked,
            reason=reason,
            slot=slot,
            weather=weather,
            inventory=inventory,
            relaxed=relaxed,
            moment=moment,
        )
        relaxed_level = outcome.relaxed_level
        effective_cook_cap = self._relax_ladder(profile)[relaxed_level]["cook_cap"]
        # 口径与 events.py 完全一致: 去空白 + 截断到列宽, 不做 UUID 校验 ——
        # 埋点宁可存下一个格式不对的值让人能查到"谁传错了", 也不要静默把整条链路丢掉。
        clean_session_id = _clean_session_id(session_id)
        result["session_id"] = clean_session_id
        # 度量字段与给用户看的 relaxed 同源自一处, 但粒度不同:
        # relaxed_level 记松弛到第几档, candidate_count 记放宽**前**的池子大小,
        # band_size 记用户真正在其中抽签的那几道。三个数合起来才看得出"选择空间"。
        result["relaxed_level"] = relaxed_level
        result["candidate_count"] = outcome.candidate_count
        result["band_size"] = outcome.band_size
        # 判塌缩看这个, 不看 band_size: 后者被 padding 保底, 塌了也看不出来
        result["natural_band_size"] = outcome.natural_band_size
        result["id"] = await self._persist(
            user_id=user_id, picked=picked, result=result, slot=slot,
            weather=weather, today=today, relaxed_level=relaxed_level,
            candidate_count=outcome.candidate_count, band_size=outcome.band_size,
            natural_band_size=outcome.natural_band_size,
            session_id=clean_session_id, reroll_index=max(0, reroll_index),
            filters=_filters_snapshot(
                profile=profile, slot=slot, excluded=excluded, intent=intent,
                relaxed_level=relaxed_level, cook_cap=effective_cook_cap,
                pool_topped_up=self._pool_topped_up,
            ),
        )
        return result

    async def last(self, user_id: int) -> Optional[Dict[str, Any]]:
        """上一次决策结果的快照 (冷启动秒开, 需求 4 的首屏不能闪空卡)"""
        stmt = (
            select(DecisionLog)
            .where(DecisionLog.user_id == user_id)
            .order_by(DecisionLog.created_at.desc(), DecisionLog.id.desc())
            .limit(1)
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        return self._from_payload(row)

    async def recent(self, user_id: int, days: int = 7) -> List[Dict[str, Any]]:
        since = datetime.now(CST).date() - timedelta(days=max(1, days))
        stmt = (
            select(DecisionLog)
            .where(DecisionLog.user_id == user_id, DecisionLog.decision_date >= since)
            .order_by(DecisionLog.created_at.desc())
            .limit(50)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "dish_name": r.dish_name,
                "meal_slot": r.meal_slot,
                "reason": r.reason,
                "source": r.source,
                "accepted": r.accepted,
                "decision_date": r.decision_date.isoformat(),
            }
            for r in rows
        ]

    async def feedback(self, user_id: int, decision_id: int, liked: bool) -> bool:
        """采纳 / 换一个。换一个会把上一次的结果标记为未采纳, 用于统计理由接受率。"""
        stmt = select(DecisionLog).where(
            DecisionLog.id == decision_id, DecisionLog.user_id == user_id
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if not row:
            return False
        row.accepted = liked
        await self.db.flush()
        return True

    async def profile_view(self, user_id: int, now: Optional[datetime] = None) -> Dict[str, Any]:
        """GET /decide/profile —— 首屏一次拿齐口味档案 + 时段 + 天气, 少一次 RTT"""
        moment = now or datetime.now(CST)
        profile = await self.load_profile(user_id)
        weather = await self.weather_service.get()
        return {
            "has_profile": profile.has_profile,
            "cuisines": profile.cuisines,
            "spice_level": profile.spice_level,
            "avoid": profile.avoid,
            "allergens": profile.allergens,
            "scene_tags": profile.scene_tags,
            "cook_cap": profile.cook_cap,
            "meal_budget": profile.meal_budget,
            "meal_slot": self._resolve_slot(None, moment),
            "weather": weather.as_dict(),
        }

    # ------------------------------------------------------------------ 档案 / 历史 / 库存

    async def load_profile(self, user_id: int) -> Profile:
        diet = (
            await self.db.execute(select(DietPreference).where(DietPreference.user_id == user_id))
        ).scalar_one_or_none()
        allergy = (
            await self.db.execute(
                select(AllergyRestriction).where(AllergyRestriction.user_id == user_id)
            )
        ).scalar_one_or_none()
        household = (
            await self.db.execute(select(Household).where(Household.user_id == user_id))
        ).scalar_one_or_none()

        cuisines = json_list(diet.cuisines) if diet else []
        spice = diet.spice_level if diet else 2
        scene = json_list(diet.scene_tags) if diet else []
        avoid = json_list(allergy.avoid_ingredients) if allergy else []
        allergens = json_list(allergy.allergens) if allergy else []

        # 出餐时间上限: 没有家庭档案时给宽松的 60 分钟,
        # 否则按"工作日做饭时长"来 —— 引导第 3 问就是写这个字段的。
        cook_cap = 60
        if household and household.weekday_cook_minutes:
            cook_cap = household.weekday_cook_minutes

        # 每餐预算: 用户在设置里给的是"一天多少钱", 这里按当日餐次摊到一餐上。
        # 周末和工作日的日预算是分开设的, 所以要先看今天是不是周末。
        meal_budget: Optional[float] = None
        budget = (await self.db.execute(select(Budget).where(Budget.user_id == user_id))).scalar_one_or_none()
        if budget:
            meals_per_day = household.meals_per_day if household and household.meals_per_day else 2
            is_weekend = datetime.now(CST).weekday() >= 5
            daily = budget.weekend_daily_budget if is_weekend else budget.weekday_daily_budget
            if daily and daily > 0:
                meal_budget = float(daily) / meals_per_day

        return Profile(
            cuisines=cuisines,
            spice_level=spice,
            avoid=avoid,
            allergens=allergens,
            scene_tags=scene,
            cook_cap=cook_cap,
            has_profile=bool(diet or allergy or household),
            meal_budget=meal_budget,
        )

    async def load_recent_history(self, user_id: int, today: date) -> RecentHistory:
        """近 N 天的事实, 来自 decision_log ∪ menu_item

        两个来源都要查: 用户点了「饭决」但没放进周菜单的决策只存在于 decision_log,
        只看 menu_item 会让"连点三次"的用户看到同一道菜循环出现。
        """
        history = RecentHistory()
        since = today - timedelta(days=self.settings.no_repeat_days)
        # (name, category, cuisine, main, spice, when: date, seq: float)
        # seq 是"这一餐在当天里的先后" —— 只按 decision_date 排序是不够的:
        # 同一天点了 3 次「饭决」, 三条记录的 decision_date 完全相同,
        # 稳定排序会让"上一餐"永远停在当天最早那一条, 连续两餐不重样就形同失效。
        entries: List[tuple] = []

        decisions = (
            await self.db.execute(
                select(DecisionLog).where(
                    DecisionLog.user_id == user_id, DecisionLog.decision_date >= since
                )
            )
        ).scalars().all()
        for d in decisions:
            spice = d.recipe.spice_level if d.recipe else None
            entries.append(
                (
                    d.dish_name,
                    d.dish_category,
                    d.dish_cuisine,
                    d.main_ingredient,
                    spice,
                    d.decision_date,
                    # 决策的 created_at 就是真实点击时间, 直接用它最准。
                    # 末尾的 id 微扰不能省: 连点几次时 created_at 会落在同一秒,
                    # 而 sort(reverse=True) 是**稳定**排序, 并列项保持插入顺序,
                    # 结果「上一餐」永远停在最早那条, 连续两餐不重样就失效了。
                    (
                        d.created_at
                        or datetime.combine(d.decision_date, time(_MEAL_HOURS.get(d.meal_slot, 12)))
                    ).timestamp()
                    + (d.id or 0) / 1000.0,
                )
            )

        rows = (
            await self.db.execute(
                select(MenuItem, Recipe)
                .join(Menu, Menu.id == MenuItem.menu_id)
                .join(Recipe, Recipe.id == MenuItem.recipe_id)
                .where(Menu.user_id == user_id, MenuItem.meal_date >= since)
            )
        ).all()
        for item, recipe in rows:
            entries.append(
                (
                    recipe.name,
                    recipe.category,
                    recipe.cuisine,
                    recipe.main_ingredient,
                    recipe.spice_level,
                    item.meal_date,
                    # menu_item 的 created_at 是"菜单生成时间", 不等于用餐时间,
                    # 所以按 meal_date + 餐次推算, 同一天里早/午/晚才分得开
                    datetime.combine(
                        item.meal_date, time(_MEAL_HOURS.get(item.meal_type, 12))
                    ).timestamp()
                    + (item.id or 0) / 1000.0,
                )
            )

        # 按时间倒序 (同日再用 seq 细分), 第一条就是"上一餐"
        entries.sort(key=lambda e: (e[5], e[6]), reverse=True)
        spread_meals = self.settings.category_spread_meals

        last_spicy_date: Optional[date] = None
        for idx, (name, category, cuisine, main, spice, when, _seq) in enumerate(entries):
            key = normalize_dish_name(name)
            history.names.add(key)
            history.dish_last_seen.setdefault(key, when)

            if idx < spread_meals:
                if category:
                    history.category_counts[category] = history.category_counts.get(category, 0) + 1
                if cuisine:
                    history.cuisine_counts[cuisine] = history.cuisine_counts.get(cuisine, 0) + 1

            if idx == 0:
                history.last_main = main
                history.last_cuisine = cuisine
                history.last_category = category

            if spice is not None and spice >= 2:
                if last_spicy_date is None or when > last_spicy_date:
                    last_spicy_date = when

        if last_spicy_date is not None:
            history.days_since_spicy = (today - last_spicy_date).days
        return history

    async def load_inventory(self, user_id: int, today: date):
        """返回 (家里现有的食材名集合, 临期食材名列表)"""
        rows = (
            await self.db.execute(
                select(Ingredient.name, FridgeInventory.expiry_date)
                .join(FridgeInventory, FridgeInventory.ingredient_id == Ingredient.id)
                .where(FridgeInventory.user_id == user_id)
            )
        ).all()
        owned = {name for name, _ in rows}
        expiring = [
            name
            for name, expiry in rows
            if expiry and expiry <= today + timedelta(days=2)
        ]
        return owned, expiring

    async def load_candidates(self) -> List[Candidate]:
        """候选池: 库里菜谱优先, 不足 20 道时用本地池补齐

        本地池是「永远有答案」的兜底 —— 新用户第一次点「饭决」时库里通常是空的。

        为什么要 is_dish 这道闸 (迁移 0017):
            库的来源是把外部菜谱站整包搬进来, 调味品/酒水/甜品/半成品也跟着进来了,
            并且它们的 category 被导入规则归成了荤菜/素菜/汤羹 —— 基于 category 的
            过滤一个都拦不住, 用户真的在结果卡上见过"油泼辣子"。
            COALESCE 而不是 `is_dish == 1`: 万一某行的值是 NULL, 宁可放行也不要让用户
            没菜吃。少一道菜是事故, 多一道奶茶只是尴尬。

        ⚠️ T01 (2026-09-23, team-lead 裁定: 加观测标记, 不改逻辑):
            **补齐进来的这批菜是零过滤的** —— 它们不经过 is_dish 之外的任何闸,
            忌口 / 过敏 / 时间上限 / 预算对它们统统不生效。于是:
              候选被砍到 < 20 时, 任何硬约束都会**静默失效** —— 用户设了忌口,
              却照样吃到忌口的菜, 而日志里看不出任何异常。
            V1.2.0 不加硬过滤, 所以现在不触发; 但它是 V1.3 的前置地雷:
            **在补齐路径上加任何硬约束之前, 先看 filters_snapshot.pool_topped_up
            为 true 的比例** —— 那个比例就是"硬约束会静默失效"的比例。
        """
        rows = (
            await self.db.execute(
                select(Recipe).where(dish_only()).limit(self.settings.local_candidate_scan)
            )
        ).scalars().all()
        candidates = [self._from_recipe(r) for r in rows]

        self._pool_topped_up = False
        if len(candidates) < 20:
            self._pool_topped_up = True
            known = {c.name for c in candidates}
            for item in LOCAL_DISHES:
                if item["name"] not in known:
                    candidates.append(self._from_pool(item))
        return candidates

    # ------------------------------------------------------------------ 挑选

    async def _understand(
        self,
        utterance: Optional[str],
        *,
        slot: str,
        inventory: set,
    ) -> Optional[MealIntent]:
        """解析一句口语诉求。任何异常都必须吞掉 —— 听不懂只是少一个加分项。"""
        if not utterance or not utterance.strip():
            return None
        try:
            return await MealIntentService().understand(
                utterance, slot=slot, fridge=sorted(inventory)[:20]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("口语诉求解析失败, 已忽略: %s", exc)
            return None

    def _relax_ladder(self, profile: Profile) -> List[Dict[str, Any]]:
        """5 档放宽阶梯 (R-10), 顺序从"最不该让用户察觉"到"最后防线"

        0  全硬规则
        1  松 cook_cap        用户最能忍的是多花十分钟, 所以先松时间
        2  松品类打散         连着几餐同品类比慢一点更烦, 排在松时间之后
        3  松主料两餐不重样   上一餐刚用过的主料可以再用
        4  松近 7 天不重复    最后防线; 走到这一档说明池子真被榨干了

        tools 和 meal_slots 不进这条阶梯:
          tools —— 家里没有烤箱却推烤羊排, 用户做不出来, 松了也没用;
          meal_slots —— 覆盖率只有两成多, 硬过滤会把池子砍到 1/4 (夜宵池刚吃过这个亏),
                        所以走 R-11: 只加分不减分, 不进 `_passes` 的过滤链。
        """
        return [
            {
                "cook_cap": profile.cook_cap,
                "no_category_penalty": False,
                "no_main_penalty": False,
                "allow_repeat": False,
            },
            {
                "cook_cap": None,
                "no_category_penalty": False,
                "no_main_penalty": False,
                "allow_repeat": False,
            },
            {
                "cook_cap": None,
                "no_category_penalty": True,
                "no_main_penalty": False,
                "allow_repeat": False,
            },
            {
                "cook_cap": None,
                "no_category_penalty": True,
                "no_main_penalty": True,
                "allow_repeat": False,
            },
            {
                "cook_cap": None,
                "no_category_penalty": True,
                "no_main_penalty": True,
                "allow_repeat": True,
            },
        ]

    def _pick(
        self,
        candidates: List[Candidate],
        profile: Profile,
        history: RecentHistory,
        weather: WeatherContext,
        inventory: set,
        expiring: List[str],
        slot: str,
        excluded: set,
        today: date,
        intent: Optional[MealIntent] = None,
    ) -> PickResult:
        """按 5 档阶梯筛到够抽签为止, 再软随机挑一个

        为什么是"池子低于水位线就提前放宽"而不是"池子空了才放宽":
        旧实现只在 pool==0 时触发, 于是用户体感是"先拿到一次明显不合时宜的结果,
        放宽才生效" —— 放宽本身没错, 错在它来得太晚。改成水位线后放宽得更早,
        代价是 relaxed_level>0 的发生率上升, 这是预期的: 用户少看一次失败。
        """
        candidate_count = 0

        # 天花板 = 全松之后最多能有多少菜。它既是"兜底时就这么多", 也决定了该瞄多大的池子:
        # 库里总共才 5 道菜的时候硬要凑够 8 道, 只会一路放宽到最深那档(连 7 天不重复都松掉),
        # 白给用户端上一道昨天刚吃过的菜, 而池子其实一点也没变大。
        ceiling = len(
            [
                c
                for c in candidates
                if self._passes(
                    c, profile, history, weather, inventory, slot, excluded,
                    cook_cap=None, allow_repeat=True,
                )
            ]
        )
        if not ceiling:
            # 理论上到不了这里: 忌口之外全松了还是没菜。交给上层明确报错。
            return PickResult(None, MAX_RELAX_LEVEL, 0, 0)

        target = min(POOL_MIN, ceiling)

        for level, relax in enumerate(self._relax_ladder(profile)):
            pool = [
                c
                for c in candidates
                if self._passes(
                    c, profile, history, weather, inventory, slot, excluded,
                    cook_cap=relax["cook_cap"], allow_repeat=relax["allow_repeat"],
                )
            ]
            if level == 0:
                # 放宽**之前**的池子大小 —— 上报它之后, 旧口径的事后重算才有可能
                candidate_count = len(pool)
            if len(pool) >= target:
                break

        scored = [
            (
                self._score(
                    c, profile, history, weather, inventory, expiring, slot,
                    intent=intent,
                    no_category_penalty=relax["no_category_penalty"],
                    no_main_penalty=relax["no_main_penalty"],
                ),
                c,
            )
            for c in pool
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        band = self._random_band(scored)
        return PickResult(
            random.choice(band), level, candidate_count, len(band), self._natural_band_size(scored)
        )

    def _natural_band_size(self, scored: List[tuple]) -> int:
        """真正在分差带里的道数 —— 不含"不足 min_choices 时补齐"的那几道

        为什么单独有这个数: `_random_band` 在真带不足 random_min_choices 时会按分数
        补齐, 于是 `band_size >= random_min_choices` 恒成立, 塌缩会被这个下限完全掩盖
        (数析实测: 真带 2 道、band_size 却是 3, 第 3 道比门槛低 7.9 分)。
        判据一律以这个数为准, band_size 只用来看"用户实际在几道里抽"。
        """
        cutoff = self._band_cutoff(scored)
        return sum(1 for score, _ in scored if score >= cutoff)

    def _band_cutoff(self, scored: List[tuple]) -> float:
        """分差带的下沿。抽签带的定义只有这一处, 别在别处重写 `best - random_band`

        用 self.settings 而不是 get_settings(): 实例上的 settings 才是这次决策真正
        生效的那份(测试里换过)。两处各取一份, band_size 和 natural_band_size 就会
        按不同的带算出来, 于是"band_size 比 natural 大出来的那截就是 padding"这个
        反查不再成立 —— 那正是 natural_band_size 存在的唯一理由。
        """
        return scored[0][0] - self.settings.random_band

    def _random_band(self, scored: List[tuple]) -> List[Candidate]:
        """软随机池: 分差在 band 之内的都参与抽签

        注意这里**不能**先取 top N 再在 N 个里随机: 那样用户连点几次「换一个」
        会在固定的 3 道菜之间来回横跳, 反而加深"这个 App 就这几道菜"的印象。
        分差带已经保证了参与抽签的都是"差不多好"的候选。
        """
        cutoff = self._band_cutoff(scored)
        band = [c for score, c in scored if score >= cutoff]
        # 分差带太窄(比如有道菜明显更好)时, 按分数补齐到最少候选数, 免得每次都同一道
        if len(band) < self.settings.random_min_choices:
            band = [c for _, c in scored[: self.settings.random_min_choices]]
        return band or [scored[0][1]]

    def _passes(
        self,
        c: Candidate,
        profile: Profile,
        history: RecentHistory,
        weather: WeatherContext,
        inventory: set,
        slot: str,
        excluded: set,
        cook_cap: Optional[int],
        allow_repeat: bool = False,
    ) -> bool:
        # 1) 忌口与过敏 —— 这条永远不松, 是安全线
        lowered = c.haystack
        for word in profile.avoid + profile.allergens:
            if word and word in lowered:
                return False

        # 2) 本次会话手动排除的(点了"换一个"之后不再出同一道)
        if normalize_dish_name(c.name) in excluded:
            return False

        # 3) 近 7 天不重复 —— 硬规则 (需求 5)
        if not allow_repeat and normalize_dish_name(c.name) in history.names:
            return False

        # 4) 深夜: 轻食, 或主食/面食类快手菜, 且够快 (需求 9)
        #    主食/面食走 LATE_NIGHT_EXTRA_CATEGORIES 白名单, 不写进 is_light —— 见常量处注释。
        #    时间上限对白名单菜同样生效, 白名单不是"深夜什么都能吃"。
        if slot == MealSlot.LATE_NIGHT:
            if not (c.light or c.category in LATE_NIGHT_EXTRA_CATEGORIES):
                return False
            if (c.minutes or 0) > self.settings.late_night_max_minutes:
                return False

        # 5) 出餐时间上限
        if cook_cap and (c.minutes or 0) > cook_cap:
            return False

        return True

    def _meal_slot_score(self, c: Candidate, slot: str) -> float:
        """meal_slots 软惩罚 (R-11)

        只加分不减分 (减分这一侧的幅度被压到 0)。为什么这么怂: 抽签走的是
        `_random_band` 的"距最优分 5 分以内都参与", 所以任何一个超过 5 分的二元打分
        都不再是"软"的 —— 见 MEAL_SLOT_MATCH_BONUS 处的新通则。
        空值 = 不限制, 不奖不罚。

        ⚠️ 与夜宵白名单的冲突在这里解开:
        被 LATE_NIGHT_EXTRA_CATEGORIES 救回来的 29 道里, 有 17 道 meal_slots 是
        ["breakfast","lunch"], 明确不含 late_night —— 正好命中"不匹配"那一侧。
        白名单把它们放进池子、软惩罚又把分压下去, 两个改动互相抵消, 深夜还是出不了面。
        所以深夜分支里命中白名单一律跳过软惩罚: 白名单是明确的人工裁决, 优先级更高。

        这条豁免在当前 MEAL_SLOT_MISMATCH_PENALTY = 0 下是**不生效的保险** ——
        不匹配本来就不扣分了, 冲突自然不存在。留着是因为: 哪天按上面的通则将减分
        调回一个非 0 的小值(dish_rules 补标注、覆盖率上来之后很可能), 冲突会立刻回来,
        而且症状是"深夜又出不了面", 极难定位源头。
        """
        if slot == MealSlot.LATE_NIGHT and c.category in LATE_NIGHT_EXTRA_CATEGORIES:
            return 0.0
        if not c.meal_slots:
            return 0.0
        return MEAL_SLOT_MATCH_BONUS if slot in c.meal_slots else MEAL_SLOT_MISMATCH_PENALTY

    def _score(
        self,
        c: Candidate,
        profile: Profile,
        history: RecentHistory,
        weather: WeatherContext,
        inventory: set,
        expiring: List[str],
        slot: str,
        intent: Optional[MealIntent] = None,
        no_category_penalty: bool = False,
        no_main_penalty: bool = False,
    ) -> float:
        s = self.settings
        score = 0.0

        # 偏好菜系
        if profile.cuisines and c.cuisine in profile.cuisines:
            score += s.score_cuisine

        # 辣度贴合: 差值越大扣越多, 最多扣满
        gap = abs((c.spice or 0) - profile.spice_level) / 4.0
        score += s.score_spice * max(0.0, 1.0 - gap)

        # 库存: 排序走命中数 (R-09), 天气/文案走命中率 —— 见 _inventory_score 处的说明
        ratio = self._inventory_ratio(c, inventory)

        # 天气 (需求 9)
        score += self._weather_score(c, weather, ratio)

        # 预算贴合: 每餐预算由日预算按餐次摊过来; 估不出价的菜不奖不罚
        if profile.meal_budget and c.cost is not None:
            if c.cost <= profile.meal_budget:
                score += s.score_budget
            elif c.cost <= profile.meal_budget * s.budget_over_tolerance:
                score += s.score_budget * 0.4
            else:
                score -= s.score_budget

        # ---- 软偏好包: 餐次贴合 / 早餐补偿 / 库存命中 / 口语诉求 ----
        #
        # 这几笔都是"倾向", 不是硬规则, 所以合成一个包再整体封顶 —— 见
        # SOFT_PREFERENCE_CAP 处的说明。单项各自 <= random_band 挡不住它们叠起来穿。
        #
        # ⚠️ 餐次贴合与早餐补偿 **取最大值, 不叠加** —— 见 BREAKFAST_CATEGORY_BONUS 处。
        #   2026-09-23 试过叠加(方案「叠加 7.5」)并被**回退**: 门禁改成结果判红后,
        #   它在 4 场景 × 补标前后 8 格里挂了 2 格(荤菜x1/补标后 natural_band=17、
        #   prefer_fridge/补标后 natural_band=13, 主食占 38.5% 已在往塌缩走)。
        #   **不要为它加防塌兜底** —— 判据不能为方案让步。
        soft = 0.0

        # 餐次贴合 (R-11): 标注了 meal_slots 的菜才知道"这一顿合不合适", 空值不奖不罚
        slot_score = self._meal_slot_score(c, slot)

        # 早餐代理补偿: 只在"没标注"或"标注含早餐"时给 —— 显式标成别的餐次就不给。
        breakfast_comp = 0.0
        if slot == MealSlot.BREAKFAST and (not c.meal_slots or slot in c.meal_slots):
            if c.category in ("主食", "面食"):
                breakfast_comp += BREAKFAST_CATEGORY_BONUS
            if (c.minutes or 0) <= 15:
                breakfast_comp += BREAKFAST_QUICK_BONUS

        soft += max(slot_score, breakfast_comp)

        # 库存命中 (R-09): 命中数 / 固定分母, 幅度封在 INVENTORY_SCORE_CAP。
        # intent 传进去不是为了加分, 是让 prefer_fridge 放大**命中数** ——
        # 它若在这笔之外单加一个 +6.0, 因为对每道菜都成立, 会把整个包烧成常数。
        soft += self._inventory_score(c, inventory, expiring, intent)

        # 口语诉求加分 (模型/规则解析)。只加分不减分, 幅度刻意压小:
        # "想吃清淡的"是倾向, 不是命令, 不该压过库存命中、菜系偏好这些硬信号。
        if intent is not None:
            soft += intent.bonus(c)

        score += min(soft, SOFT_PREFERENCE_CAP)

        # 同品类打散 (需求 5)。no_category_penalty 由放宽阶梯第 2 档打开。
        if not no_category_penalty:
            if c.category:
                count = history.category_counts.get(c.category, 0)
                score -= s.category_penalty_step * count
            if c.cuisine and c.cuisine == history.last_cuisine:
                score -= s.same_cuisine_penalty

        # 连续两餐不重样: 主料重合 (需求 5)。第 3 档放宽时才绕过。
        if not no_main_penalty:
            if history.last_main and c.main and history.last_main == c.main:
                score -= s.main_ingredient_penalty

        # ⚠️ intent.bonus() 只在上面的软偏好包里加一次, 这里不要再补一笔:
        # 补在包外等于绕过了 SOFT_PREFERENCE_CAP —— 包的意义就是"倾向类加成合起来看",
        # 漏一笔在外面, 静态自检扫的是包、实际生效的是包外那笔, 又是一次静默失效。
        return score

    # 调味料不算"家里有", 否则几乎每道菜都满分。
    _STAPLES = {"盐", "食用油", "糖", "生抽", "老抽", "香油", "淀粉", "料酒", "白胡椒", "黑胡椒"}

    @classmethod
    def _needed_ingredients(cls, c: Candidate) -> List[str]:
        """这道菜真正要买的食材 (去掉调味料)

        ⚠️ 这个函数同时是分子(hits)和分母(len) —— 改剔除范围会**两边一起变**,
        连带改变两个消费点的触发率:
          1. _weather_score 的雨天门槛 (ratio >= 0.3)
          2. 「交给外卖吧」文案 (ratio < 0.3, _build_result)
        后者是**用户可见**的: 用户什么都没做, 文案出现频率就变了。

        葱姜蒜的剔除就是卡在这条上被撤掉的(三个方案实测全部超 ±5pp), 理由与实测
        数据见模块级「葱 / 姜 / 蒜」那段注释 —— V1.3 拆成两份 need 再做。
        """
        if not c.ingredients:
            return []
        return [i for i in c.ingredients if i not in cls._STAPLES]

    @classmethod
    def _inventory_hits(cls, c: Candidate, inventory: set) -> int:
        """家里现有的食材命中了几样 —— R-09 排序用的分子

        分母不再是这道菜自己的食材数: 那样"2 样食材的菜录中 1 样"就能拿满,
        等于奖励食材少的简单菜。固定分母见 INVENTORY_HITS_FULL。
        """
        need = cls._needed_ingredients(c)
        if not inventory or not need:
            return 0
        return sum(1 for i in need if any(i in owned or owned in i for owned in inventory))

    @classmethod
    def _inventory_ratio(cls, c: Candidate, inventory: set) -> float:
        """命中率 hits/len(need) —— 供天气加分与「交给外卖吧」文案用

        ⚠️ R-09 一行不改。这两个消费点的触发率有改动前基线盯着:
        data-analyst 拍了三组快照的触发率 + 菜名集合指纹, 动一个字都会红。
        """
        if not inventory or not c.ingredients:
            return 0.0
        need = cls._needed_ingredients(c)
        if not need:
            return 0.0
        return cls._inventory_hits(c, inventory) / len(need)

    def _inventory_score(
        self,
        c: Candidate,
        inventory: set,
        expiring: List[str],
        intent: Optional[MealIntent] = None,
    ) -> float:
        """库存家族的排序加分 (命中 + 临期), 合起来不超过 INVENTORY_SCORE_CAP

        为什么"合起来"封顶: 两笔都是库存派生量, 各封 5 分叠起来是 10,
        照样能把抽签带切成"抽得到 / 抽不到"两半 —— 见 INVENTORY_SCORE_CAP 处的说明。

        intent.prefer_fridge 在这里生效, 放大的是**命中数**、在归一化之前:
        这样"录中 1 样"的菜拿到 1.5 样而不是 2 样, 保住了连续型(没录中的仍是 0),
        也不会给一道家里一样都没有的菜白送分 —— 见 PREFER_FRIDGE_MULTIPLIER。
        """
        s = self.settings
        hits: float = self._inventory_hits(c, inventory)
        if intent is not None and getattr(intent, "prefer_fridge", False):
            hits *= PREFER_FRIDGE_MULTIPLIER
        # 连续型而不是命中/不命中二选一: 录中 1 样就该比没录中强, 但不必一步登天
        bonus = min(s.score_inventory, INVENTORY_SCORE_CAP) * min(hits, INVENTORY_HITS_FULL) / INVENTORY_HITS_FULL
        # 临期食材命中, 额外加权: 能顺手清掉快坏的东西
        if expiring and any(e in ing for e in expiring for ing in c.ingredients):
            bonus += s.score_inventory * 0.4
        return min(bonus, INVENTORY_SCORE_CAP)

    @staticmethod
    def _weather_score(c: Candidate, weather: WeatherContext, inventory_ratio: float) -> float:
        """天气加权。weather.condition 为 None 时整体跳过 —— 不知道不等于晴天。"""
        if weather.condition is None:
            return 0.0
        s = get_settings().decide
        tags = set(c.tags)

        if weather.is_bad:
            # 下雨/下雪: 优先"家里有料"的菜 (少出门), 汤羹炖煮也加分
            score = 0.0
            if inventory_ratio >= 0.3:
                score += s.score_weather
            elif inventory_ratio >= 0.1:
                score += s.score_weather * 0.5
            if tags & {"汤羹", "炖煮", "一锅出", "雨天"}:
                score += s.score_weather * 0.6
            return score

        if weather.is_hot:
            score = 0.0
            if tags & {"清爽", "凉拌"} or "清爽" in c.flavors:
                score += s.score_weather
            if (c.spice or 0) >= 3 or "热辣" in tags:
                score -= 15.0
            return score

        if weather.is_cold:
            score = 0.0
            if tags & {"汤羹", "炖煮", "热辣"} or "辣" in c.flavors:
                score += s.score_weather
            if "凉拌" in tags or (c.category == "凉菜"):
                score -= 20.0
            return score

        return 0.0

    # ------------------------------------------------------------------ 理由 / 结果

    def _build_reason(
        self,
        picked: Candidate,
        history: RecentHistory,
        weather: WeatherContext,
        expiring: List[str],
        inventory: set,
        slot: str,
        relaxed: bool,
        today: date,
    ) -> str:
        last_seen = history.dish_last_seen.get(normalize_dish_name(picked.name))
        days_since = (today - last_seen).days if last_seen else None
        hit_expiring = next((e for e in expiring if any(e in i for i in picked.ingredients)), None)

        ctx = ReasonContext(
            dish=picked.name,
            days_since_spicy=history.days_since_spicy,
            days_since_dish=days_since,
            expiring_item=hit_expiring,
            weather=weather.condition,
            meal_slot=slot,
            cuisine=picked.cuisine,
            cuisine_rotated=bool(picked.cuisine and picked.cuisine != history.last_cuisine),
            # ⚠️ 不再传 minutes: cook_minutes 是规则回填的品类基准值(119 道菜都是 22),
            # 「{n} 分钟搞定」那条理由已整条摘掉(见 reason_service 的注释)。
            inventory_ratio=self._inventory_ratio(picked, inventory),
            relaxed=relaxed,
        )
        return self.reason_service.build(ctx)

    def _build_result(
        self,
        picked: Candidate,
        reason: str,
        slot: str,
        weather: WeatherContext,
        inventory: set,
        relaxed: bool,
        moment: datetime,
    ) -> Dict[str, Any]:
        # 雨天 + 家里没料 → 明确给"交给外卖吧"的次级出口 (需求 9)
        advice = None
        if weather.is_bad and self._inventory_ratio(picked, inventory) < 0.3:
            advice = "这种天出门不值当，交给外卖吧"
        if relaxed:
            advice = advice or "可选项不多，放宽了一点条件"

        return {
            "id": 0,  # _persist 后回填
            "dish": {
                "recipe_id": picked.id,
                "name": picked.name,
                "cuisine": picked.cuisine,
                "category": picked.category,
                "cover_text": picked.cover,
                "cook_minutes": picked.minutes,
                "calories": picked.calories,
                "difficulty": picked.difficulty,
                "main_ingredient": picked.main,
                "ingredients": picked.ingredients,
                "steps": self._clip_steps(picked.steps),
                # 所需厨具, 纯展示。前端已按可空实现: 拿到空数组就不渲染这一行
                "tools": picked.tools,
            },
            "reason": reason,
            "meal_slot": slot,
            "meal_slot_label": MealSlot.LABELS.get(slot, ""),
            "source": DecisionSource.LOCAL if not picked.from_pool else DecisionSource.LOCAL,
            "weather": weather.as_dict(),
            "advice": advice,
            "relaxed": relaxed,
            "decided_at": moment.isoformat(),
        }

    def _clip_steps(self, steps: Iterable[str]) -> List[str]:
        """极简做法卡: 严格 3-5 步 (需求 10)。不足 3 步不硬凑, 超过 5 步只取前 5。"""
        s = self.settings
        items = [str(x) for x in (steps or []) if str(x).strip()]
        if len(items) > s.quick_steps_max:
            return items[: s.quick_steps_max]
        return items

    async def _persist(
        self,
        user_id: int,
        picked: Candidate,
        result: Dict[str, Any],
        slot: str,
        weather: WeatherContext,
        today: date,
        relaxed_level: int = 0,
        candidate_count: int = 0,
        band_size: Optional[int] = None,
        natural_band_size: Optional[int] = None,
        session_id: Optional[str] = None,
        reroll_index: int = 0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        row = DecisionLog(
            user_id=user_id,
            recipe_id=picked.id if not picked.from_pool else None,
            dish_name=picked.name,
            dish_category=picked.category,
            dish_cuisine=picked.cuisine,
            main_ingredient=picked.main,
            decision_date=today,
            meal_slot=slot,
            source=result.get("source") or DecisionSource.LOCAL,
            reason=result.get("reason"),
            weather=weather.condition,
            payload=json.dumps(result, ensure_ascii=False),
            # J3 的三列: 有没有放宽 + 放宽前池子多大 + 实际抽签带多大。
            # relaxed 由 relaxed_level 派生, 不从 payload 里反推 —— 两个来源迟早会打架,
            # 而 payload 是给前端渲染的 UI 快照, 指标不能建在它上面。
            relaxed=relaxed_level > 0,
            relaxed_level=relaxed_level,
            candidate_count=candidate_count,
            # NULL = 当时没测到, 绝不等于 0 道: 0 是"抽签带空了"的缺陷信号,
            # 缺值伪造出来的 0 会污染 decide_empty_pool 告警。
            band_size=band_size,
            # 和 band_size 不是一回事, 也不能互相顶替: band_size 被 padding 保过底,
            # 真带塌到 1 道时它仍是 3 —— J6'/J7' 判塌缩只能用这一列。
            natural_band_size=natural_band_size,
            session_id=session_id,
            reroll_index=reroll_index,
            filters_snapshot=filters,
        )
        self.db.add(row)
        await self.db.flush()
        if row.payload:
            # id 要回填进快照, 否则 /decide/last 拿到的 id 是 0, 前端点反馈会打空
            snapshot = json.loads(row.payload)
            snapshot["id"] = row.id
            row.payload = json.dumps(snapshot, ensure_ascii=False)
            await self.db.flush()
        return row.id

    @staticmethod
    def _from_payload(row: DecisionLog) -> Optional[Dict[str, Any]]:
        if not row.payload:
            return None
        try:
            return json.loads(row.payload)
        except json.JSONDecodeError:
            logger.warning("决策快照解析失败 id=%s", row.id)
            return None

    # ------------------------------------------------------------------ 候选转换

    @staticmethod
    def _from_recipe(r: Recipe) -> Candidate:
        ingredient_names = [
            ri.ingredient.name for ri in (r.recipe_ingredients or []) if ri.ingredient
        ]
        return Candidate(
            id=r.id,
            name=r.name,
            cuisine=r.cuisine or "",
            category=r.category or "",
            main=r.main_ingredient or "",
            minutes=r.cook_minutes or 30,
            calories=r.calories or 0,
            difficulty=r.difficulty or 2,
            spice=r.spice_level or 0,
            light=bool(r.is_light),
            cover=r.cover_text or "",
            tags=json_list(r.tags),
            flavors=json_list(r.flavor_tags),
            ingredients=ingredient_names,
            steps=json_list(r.quick_steps) or _split_steps(r.steps),
            meal_slots=json_list(r.meal_slots),
            tools=json_list(r.tools),
            cost=DecisionService._recipe_cost(r),
        )

    @staticmethod
    def _recipe_cost(r: Recipe) -> Optional[float]:
        """按食材参考单价估一道菜的成本; 一个价都查不到时返回 None"""
        rows = [
            PricedRow(
                ingredient_name=ri.ingredient.name or "",
                quantity=ri.quantity,
                unit=ri.unit or "",
                reference_price=ri.ingredient.reference_price,
                standard_unit=ri.ingredient.standard_unit or "",
            )
            for ri in (r.recipe_ingredients or [])
            if ri.ingredient is not None
        ]
        if not rows:
            return None
        estimate = PricingService().estimate(rows)
        if estimate.priced_items == 0:
            return None
        return estimate.total

    @staticmethod
    def _from_pool(item: Dict[str, Any]) -> Candidate:
        return Candidate(
            id=None,
            name=item["name"],
            cuisine=item.get("cuisine") or "",
            category=item.get("category") or "",
            main=item.get("main") or "",
            minutes=item.get("minutes") or 30,
            calories=item.get("calories") or 0,
            difficulty=item.get("difficulty") or 2,
            spice=item.get("spice") or 0,
            light=bool(item.get("light")),
            cover=item.get("cover") or "",
            tags=list(item.get("tags") or []),
            flavors=list(item.get("flavors") or []),
            ingredients=list(item.get("ingredients") or []),
            steps=list(item.get("steps") or []),
            meal_slots=list(item.get("slots") or []),
            # 本地池这道候选里没有厨具信息: 不下发标签比下发一个错的强。
            # 前端已按可空实现 —— 不下发就不渲染那一行。
            tools=list(item.get("tools") or []),
            from_pool=True,
        )

    # ------------------------------------------------------------------ 工具

    def _resolve_slot(self, meal_slot: Optional[str], moment: datetime) -> str:
        """时段 → 餐次槽位。显式指定优先, 否则按本地时间推断。"""
        if meal_slot in MealSlot.ALL:
            return meal_slot
        hour = moment.hour
        if hour >= self.settings.late_night_from or hour < self.settings.late_night_to:
            return MealSlot.LATE_NIGHT
        if hour < 10:
            return MealSlot.BREAKFAST
        if hour < 15:
            return MealSlot.LUNCH
        return MealSlot.DINNER


def _split_steps(raw: Optional[str]) -> List[str]:
    """老菜谱的 steps 是一整段文本, 按行拆一下顶上去"""
    if not raw:
        return []
    return [line.strip(" 0123456789.、)）") for line in raw.splitlines() if line.strip()]
