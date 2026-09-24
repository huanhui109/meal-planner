"""口语诉求解析 —— System One 决策模型在本项目里的主要落点

为什么落在这里:
    饭决的核心决策链路(忌口过滤 / 7 天不重复 / 品类打散 / 库存命中)全是硬规则,
    跑得快、说得清、还能被小程序离线层复现。把打分换成模型判断既慢又不可离线,
    属于典型的"拿 System One 干 System Two 的活"。
    规则真正做不了的是: 用户**用一句口语**表达诉求 —— "今天想吃清淡点的, 别太辣,
    冰箱里还有鸡蛋"。这句话没法用关键词穷举, 而这恰好是 System One 的强项:
    一次调用并行求解多个类型化问题, 直接返回结构化结果, 不需要解析自由文本、
    也不会说瞎话。

    所以分工是: **模型负责「听懂」, 规则负责「决定」**。听不懂就当没听见, 照常出菜。

两条并行的解析路径:
    模型路径   provider=laya(默认) / jev / adapter 时走, 一次调用问完全部问题。
    规则路径   provider=rule, 或模型调用失败/置信度不足时兜底。
               规则只能覆盖高频说法, 覆盖不到就返回 understood=False ——
               宁可"没听懂", 也不要猜错之后强行改用户的菜。

已知坑 (中文场景):
    Laya 的 English 权重遇到非拉丁字符会**静默失效**(不报错, 只是判得差), 所以
    中文必须用 multilingual 权重或 auto 路由。另外 Laya 零样本能力一般, 本项目
    的 NOUL_ACCEPT / NOUL_REJECT 两个阈值就是留给你用真实中文语料调的,
    不要照抄默认值上线。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.config import get_settings
from app.services.system_one_service import (
    ChoiceQ,
    NoulQ,
    ScoreQ,
    SystemOneResult,
    SystemOneService,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ 阈值

# 默认值, 实际取值来自 SystemOneSettings.noul_accept / noul_reject ——
# 因为这两个数必须能用真实中文语料重拟合, 写死在代码里等于没法调。
# Noul 返回的是"该陈述为真"的概率, 中间地带表示模型自己也没把握, 这时**不采纳**,
# 让它退回规则结果, 比强行二值化更稳。
#
# 0.91 / 0.20 是 scripts/system_one_calibrate.py 在 data/utterance_corpus.json
# (106 条中文语料 × 6 个问题 = 636 个判断点) 上按"误加约束罚 2 分、漏约束罚 1 分"
# 的非对称代价拟合出来的, 不是拍脑袋。同批数据上的实测对比:
#     纯规则                       精确率 88%  召回 75%  F1 0.81
#     纯模型(阈值 0.75/0.35)       精确率 60%  召回 72%  F1 0.65   ← 比纯规则还差
#     模型优先 + 不确定补规则       精确率 86%  召回 87%  F1 0.86
# 所以这两个数必须和 _from_model 的**逐维度融合**一起用: 模型只在高置信区发言,
# 中间地带交给规则。改阈值不跑语料等于盲改。
NOUL_ACCEPT = 0.91
NOUL_REJECT = 0.20

# 赶时间时认可的出餐上限(分钟)
RUSH_MAX_MINUTES = 20

_MEAT_WORDS = ("猪", "牛", "羊", "鸡", "鸭", "鹅", "肉", "排骨", "火腿", "培根", "香肠", "鱼", "虾", "蟹", "贝")

# 含荤字但不是荤的, 必须**先整条抠掉**再判 —— 否则「鸡蛋」含「鸡」被判成荤、
# 「鸡精」含「鸡」被判成肉, 用户说"吃素"却连番茄炒蛋都吃不上。
# 这个坑和菜谱字段推断里遇到的是同一个(见 test_recipe_field_rules.py)。
_MEAT_FALSE_POSITIVES = (
    "鸡蛋", "鸭蛋", "鹅蛋", "鹌鹑蛋", "皮蛋", "咸蛋", "蛋",
    "鸡精", "鸡粉", "鸡汁",
)


def _looks_like_meat(text: str) -> bool:
    """判断一道菜是否含荤。先抠假阳性词, 再匹配荤字"""
    cleaned = text or ""
    for word in _MEAT_FALSE_POSITIVES:
        cleaned = cleaned.replace(word, "")
    return any(w in cleaned for w in _MEAT_WORDS)


def _verdict(noul: float, accept: float = NOUL_ACCEPT, reject: float = NOUL_REJECT) -> Optional[bool]:
    """把 0-1 概率折叠成三态: True / False / None(不采纳)"""
    if noul >= accept:
        return True
    if noul <= reject:
        return False
    return None


# ------------------------------------------------------------------ 意图

@dataclass(frozen=True)
class MealIntent:
    """一句口语解析出来的结构化诉求

    understood=False 表示"没听懂或没把握"。调用方此时应当**完全忽略**这个意图,
    而不是拿默认值去过滤 —— 半套模型判断混半套规则最难排查。
    """

    utterance: str = ""
    source: str = "rule"  # laya | jev | adapter | rule
    understood: bool = False
    confidence: float = 0.0
    intent_type: Optional[str] = None  # 模型判的诉求类型, 仅供诊断/后续扩展

    require_light: bool = False    # 只要轻食
    max_spice: int = -1            # -1 = 未指定; 0..3 为可接受辣度上限
    max_minutes: Optional[int] = None
    prefer_fridge: bool = False    # 优先用冰箱现有食材
    avoid_meat: bool = False
    cuisine: Optional[str] = None
    category: Optional[str] = None  # 汤 | 主食 | 面食 等
    avoid: List[str] = field(default_factory=list)  # 明确不要的关键词

    @property
    def has_constraints(self) -> bool:
        return any(
            (
                self.require_light,
                self.max_spice >= 0,
                self.max_minutes is not None,
                self.avoid_meat,
                self.cuisine,
                self.category,
                self.avoid,
            )
        )

    def allows(self, candidate: Any) -> bool:
        """候选菜是否满足这条诉求

        注意这里只做**减法**。加分交给 bonus(), 因为诉求里的偏好不该把不匹配的
        菜直接砍掉 —— "想吃清淡的"不等于"非清淡不可", 除非候选里真的有清淡的。
        """
        if self.require_light and not candidate.light:
            return False
        if self.max_spice >= 0 and (candidate.spice or 0) > self.max_spice:
            return False
        if self.max_minutes is not None and (candidate.minutes or 0) > self.max_minutes:
            return False
        if self.avoid_meat and _looks_like_meat(candidate.haystack):
            return False
        if self.category and candidate.category != self.category:
            return False
        if self.avoid:
            hay = candidate.haystack
            if any(word in hay for word in self.avoid):
                return False
        return True

    def bonus(self, candidate: Any) -> float:
        """诉求加分。只加分不减分, 幅度刻意压小 —— 口语诉求是"倾向", 不是命令。"""
        s = 0.0
        # ⚠️ 这一条受 random_band 的约束: 抽签是"距最优分 5 分以内都参与", 所以任何
        # 二元加分的幅度一旦 > 5.0, 受加分的菜会把最优分抬高、把其他人挤出抽签带,
        # 用户连点几次「换一个」就只剩这一类菜。改这个数之前先算 幅度 vs random_band
        # (config/default.yaml 的 decide.random_band, 当前 5.0)。
        #
        # ⚠️ 另一条通则: 这里只能放**会因菜而异**的加分。全量加分(每道菜都拿到同一笔)
        # 一律不许进 —— 它会烧光软偏好包的预算, 让包里其他项集体失去区分度。
        # prefer_fridge 就是因为这条被移出去的, 详见下方注释。
        #
        # cuisine +15.0 是颗哑弹: recipe.cuisine 列现在装的是菜品分类(荤菜/主食…),
        # 和用户说出口的"川湘/粤菜"对不上, 命中率极低。但它是**休眠**的隐患而不是
        # 不存在 —— 等 V1.3 把 cuisine 列清成真菜系, 这条会原样重演: 用户说一句
        # "想吃川菜", 抽签带里就全是川菜。修 cuisine 时必须一起把这里的幅度带上。
        if self.cuisine and candidate.cuisine == self.cuisine:
            s += 15.0
        # prefer_fridge 不在这里加分 —— 它改为放大 inventory 的命中数, 见
        # decision_service.PREFER_FRIDGE_MULTIPLIER。
        # 原因: `candidate.ingredients` 对几乎每一道菜都非空, 于是这一笔是**全量加分**
        # (每道菜都拿到同样的 6.0)。全量加分放进一个有预算上限的软偏好包, 等于用常数
        # 把预算烧光 —— 包被顶到 SOFT_PREFERENCE_CAP 之后, 早餐补偿 / meal_slots /
        # 库存命中三项同时失去区分度。而 prefer_fridge 的语义恰恰是"更想用冰箱食材",
        # 被它挤掉的正是库存信号: 用户最想用冰箱食材的那一刻, 库存信号正好失效。
        # 压小幅度救不了 —— 只要它是全量的, 压到 1.0 照样烧掉预算且区分度仍为零。
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "utterance": self.utterance,
            "source": self.source,
            "understood": self.understood,
            "confidence": round(self.confidence, 3),
            "intent_type": self.intent_type,
            "require_light": self.require_light,
            "max_spice": self.max_spice,
            "max_minutes": self.max_minutes,
            "prefer_fridge": self.prefer_fridge,
            "avoid_meat": self.avoid_meat,
            "cuisine": self.cuisine,
            "category": self.category,
            "avoid": list(self.avoid),
        }


EMPTY_INTENT = MealIntent()


# ------------------------------------------------------------------ 规则兜底

_LIGHT_RE = re.compile(r"清淡|清爽|不油|少油|轻食|减脂|素一点|凉拌|不腻")
_SPICE_RE = re.compile(r"不辣|别太辣|不吃辣|少辣|忌辣|微辣|一点辣")
_RUSH_RE = re.compile(r"赶时间|着急|马上|快点|十分钟|\d+分钟|快手|简单点|随便")
_MEAT_RE = re.compile(r"吃素|素食|不吃肉|不要肉|素一点|斋")
_SOUP_RE = re.compile(r"喝汤|来个汤|汤")
# 「不要花生」「不吃香菜」「别放葱」—— 抠出被否定的那个词
_AVOID_RE = re.compile(r"(?:不要|不吃|别放|别加|忌|不放|少放)([\u4e00-\u9fa5]{1,4})")

# 「今天不想吃清淡的」「别给我汤」—— 关键词匹配最容易犯的错就是**看不见否定**:
# 里面明明有"清淡"两个字, 意思却是反的。语料里 21 条残余误判有 5 条是这个。
#
# 只对**正向偏好**类关键词(清淡 / 赶时间 / 冰箱 / 喝汤)做否定切除。排除型关键词
# (不吃辣 / 不吃肉)本身就是否定形式, 再否定一次就反了 —— "不吃辣"必须命中。
_NEG_CUES = ("不想", "不爱", "不要", "不用", "没有", "不是", "别给", "别上", "戒")
_CLAUSE_SPLIT_RE = re.compile(r"[，,。！？!?；;、\s]+")
# 「冰箱空了, 得买菜」: 提到了冰箱, 但意思恰恰是没有食材可用
_FRIDGE_RE = re.compile(r"冰箱(?!\s*(?:空|没|光))|家里有|现有|剩下的|别浪费|存货")


def _strip_negations(text: str) -> str:
    """把含否定词的分句整段抠掉, 只给正向偏好类关键词用"""
    kept = [c for c in _CLAUSE_SPLIT_RE.split(text) if not any(cue in c for cue in _NEG_CUES)]
    return "，".join(kept)


def _rule_understand(utterance: str) -> MealIntent:
    """关键词兜底

    只覆盖高频说法。匹配不到就 understood=False, 让上游照常出菜 —— 猜错的代价
    (用户想吃辣结果全是清淡) 远大于没听懂的代价 (照常推荐)。
    """
    text = utterance.strip()
    if not text:
        return EMPTY_INTENT

    # 正向偏好(清淡/赶时间/冰箱/喝汤)在**切掉否定分句**的文本上匹配;
    # 排除型诉求(不吃辣/不吃肉/不要X)在原文上匹配 —— 它们本身就是否定形式。
    positive = _strip_negations(text)

    max_spice = -1
    if _SPICE_RE.search(text):
        # "微辣" 留一点余地, 其余一律按"不吃辣"处理
        max_spice = 1 if "微辣" in text or "一点辣" in text else 0

    avoid = [w for w in _AVOID_RE.findall(text) if len(w) >= 1]
    understood = bool(
        _LIGHT_RE.search(positive)
        or _SPICE_RE.search(text)
        or _RUSH_RE.search(positive)
        or _FRIDGE_RE.search(positive)
        or _MEAT_RE.search(text)
        or _SOUP_RE.search(positive)
        or avoid
    )
    if not understood:
        return MealIntent(utterance=text, source="rule", understood=False)

    return MealIntent(
        utterance=text,
        source="rule",
        understood=True,
        confidence=0.5,  # 规则匹配无法给出校准置信度, 给个中性值
        require_light=bool(_LIGHT_RE.search(positive)),
        max_spice=max_spice,
        max_minutes=RUSH_MAX_MINUTES if _RUSH_RE.search(positive) else None,
        prefer_fridge=bool(_FRIDGE_RE.search(positive)),
        avoid_meat=bool(_MEAT_RE.search(text)),
        category="汤" if _SOUP_RE.search(positive) else None,
        avoid=avoid,
    )


# ------------------------------------------------------------------ 服务

class MealIntentService:
    """把一句口语变成结构化诉求"""

    def __init__(self, settings=None, engine: Optional[SystemOneService] = None) -> None:
        self.settings = settings or get_settings().system_one
        self.engine = engine or SystemOneService(self.settings)

    async def understand(
        self,
        utterance: str,
        *,
        slot: str = "",
        fridge: Optional[Sequence[str]] = None,
    ) -> MealIntent:
        text = (utterance or "").strip()
        if not text:
            return EMPTY_INTENT

        # 没开启 / 不可用时直接走规则, 不打任何外部电话
        if not self.engine.usable:
            return _rule_understand(text)

        # Laya 的输入预算是 512 token/问题, 冰箱清单要截断, 别把预算吃光
        state: Dict[str, Any] = {"utterance": text}
        if slot:
            state["meal_slot"] = slot
        if fridge:
            state["fridge"] = list(fridge)[:30]

        result = await self.engine.evaluate(state, _questions())
        if not result.ok:
            logger.info("System One 未返回可用判断, 口语诉求走规则兜底: %s", result.error)
            return _rule_understand(text)

        return _from_model(
            text,
            result,
            min_confidence=self.settings.min_confidence,
            accept=self.settings.noul_accept,
            reject=self.settings.noul_reject,
        )


# ------------------------------------------------------------------ 问题集

_CUISINE_OPTIONS = {
    "川湘": "麻辣、重口味、水煮、干锅一类",
    "粤菜": "清淡、蒸、白切、煲汤一类",
    "江浙": "浓油赤酱、甜口、红烧一类",
    "西北": "面食、牛羊肉、烤制一类",
    "日韩": "寿司、拉面、石锅、泡菜一类",
    "西餐": "意面、沙拉、牛排、芝士一类",
    "家常": "普通家常炒菜, 没有明显地域特征",
    "无所谓": "没有表达菜系偏好, 或看不出来",
}

_INTENT_OPTIONS = {
    "point_dish": "直接点名了某一道具体的菜",
    "describe_taste": "描述口味、口感或冷热等偏好",
    "describe_ingredient": "描述想用或不想用的食材",
    "describe_scene": "描述场景、心情或时间压力",
    "ask_directly": "只是问今天吃什么, 没有附加条件",
    "other": "以上都不是",
}


def _questions() -> Dict[str, Any]:
    """一组问题一次并行求解 —— 这是 System One 的关键用法, 加问题几乎不增加耗时

    ⚠ Noul 的 instructions 一律写成「用户**明确说出了**……」, 不要写成「用户想不想……」。

    这是实测出来的, 不是文风偏好。写成"用户想吃素吗"时, Laya 回答的是"这句话
    是否成立/合理", 而不是"用户说没说", 于是用户根本没提到的"想吃素"拿到 0.715、
    "想喝汤"拿到 0.682 —— 和真实命中项(0.80~0.96)贴得极近, 靠调阈值根本分不开
    (0.78 会把真实的"赶时间"也卡掉)。

    改成"用户明确说出了想吃素"后, 同一句话的实测:
        真信号  赶时间 0.7986 → 0.8738,  清淡 0.9603 → 0.9534, 冰箱 0.8721 → 0.8541
        假信号  想吃素 0.7148 → 0.6051,  想喝汤 0.6815 → 0.3308
    真假间距从 0.08 拉开到 0.25 以上。改措辞比调阈值有效得多。
    """
    return {
        "intent_type": ChoiceQ("这句话主要属于哪种诉求", _INTENT_OPTIONS),
        "require_light": NoulQ("用户明确说出了想吃清淡、不油腻"),
        "avoid_spicy": NoulQ("用户明确说出了不要吃辣，或要求辣度很低"),
        "rush": NoulQ("用户明确说出了自己赶时间、要求出餐快"),
        "use_fridge": NoulQ("用户明确提到了冰箱里现有的食材，希望优先用掉"),
        "avoid_meat": NoulQ("用户明确说出了要吃素、不吃肉"),
        "want_soup": NoulQ("用户明确说出了想喝汤"),
        "spice_tolerance": ScoreQ(
            "用户明确要求的辣度上限",
            ["完全不吃辣", "微辣", "中辣", "很辣"],
        ),
        "cuisine": ChoiceQ("用户明确说出了想吃哪个菜系", _CUISINE_OPTIONS),
    }


def _from_model(
    utterance: str,
    result: SystemOneResult,
    min_confidence: float = 0.55,
    accept: float = NOUL_ACCEPT,
    reject: float = NOUL_REJECT,
) -> MealIntent:
    """把 System One 答案翻成 MealIntent

    **按问题逐个把关, 不做全局开关。** 这一点踩过坑: 最初用 intent_type(六选一)
    的置信度做总闸, 结果模型给它 0.25 就把整批判断全否了 —— 而 intent_type
    本身根本没参与构建意图, 白白拖累了一堆判断正确的 noul。
    多路 Choice 天然比二值 Noul 置信度低, 拿它当总闸等于让最弱的一环决定全部。

    各原语的把关方式也不同:
      Noul  用 accept/reject 两个阈值折叠成三态(中间地带不采纳);
            Jev 的 Noul 不带 confidence, Laya 带 max(p, 1-p), 但这里统一用阈值,
            因为阈值是能用真实语料重拟合的, 而 confidence 不是。
      Choice/Score  用各自的 confidence 单独把关, 不过关就只丢这一条。

    融合策略是**逐维度**的, 不是整体二选一:
        模型判 True/False(有把握) → 听模型
        模型判 None(中间地带)     → 听规则
    这是 106 条语料实测选出来的。原先"全部落在不确定区才整体退回规则"的写法,
    在真实阈值下几乎永远走模型, 而零样本模型的精确率只有 60% —— 结果模型路径比
    纯规则还差(F1 0.65 vs 0.81)。改成逐维度融合后 0.86。
    """
    rule = _rule_understand(utterance)
    adopted_conf: List[float] = []

    intent_type = None
    if result.confidence("intent_type") >= min_confidence:
        intent_type = result.choice("intent_type")

    light = _verdict(result.noul("require_light"), accept, reject)
    spicy = _verdict(result.noul("avoid_spicy"), accept, reject)
    rush = _verdict(result.noul("rush"), accept, reject)
    fridge = _verdict(result.noul("use_fridge"), accept, reject)
    meat = _verdict(result.noul("avoid_meat"), accept, reject)
    soup = _verdict(result.noul("want_soup"), accept, reject)

    max_spice = -1
    spice_from_model = False
    if spicy is True:
        # 说"别太辣"时给微辣留一点余地, 别把候选砍空
        max_spice = 1 if result.score("spice_tolerance") >= 1.0 else 0
        spice_from_model = True
    elif spicy is None:
        # 模型没把握: 先听规则的, 规则也没有才看 Score
        max_spice = rule.max_spice
        if max_spice < 0 and result.has("spice_tolerance") and \
                result.confidence("spice_tolerance") >= min_confidence:
            max_spice = int(round(result.score("spice_tolerance")))
            adopted_conf.append(result.confidence("spice_tolerance"))
            spice_from_model = True

    cuisine = None
    cuisine_conf = result.confidence("cuisine")
    if cuisine_conf >= min_confidence:
        picked = result.choice("cuisine")
        if picked and picked != "无所谓":
            cuisine = picked
            adopted_conf.append(cuisine_conf)

    decisive = [v for v in (light, spicy, rush, fridge, meat, soup) if v is not None]
    if not decisive and not spice_from_model and not cuisine:
        # 模型一条都没把握 —— 整体交给规则, 并且把 source 标成 rule,
        # 免得线上日志看着像"模型在工作", 实际全是规则出的结果。
        logger.info("System One 全部判断都落在不确定区, 整体退回规则兜底")
        return rule

    def merge(v: Optional[bool], fallback: bool) -> bool:
        """模型有把握就听模型(包括判"没这回事"), 没把握才用规则补位"""
        return fallback if v is None else bool(v)

    require_light = merge(light, rule.require_light)
    max_minutes = RUSH_MAX_MINUTES if merge(rush, rule.max_minutes is not None) else None
    prefer_fridge = merge(fridge, rule.prefer_fridge)
    avoid_meat = merge(meat, rule.avoid_meat)
    category = "汤" if merge(soup, rule.category == "汤") else None
    # 抠"不要X"这类硬否定交给规则更准

    return MealIntent(
        utterance=utterance,
        source=result.provider,
        understood=bool(
            require_light or max_spice >= 0 or max_minutes or prefer_fridge
            or avoid_meat or cuisine or category or rule.avoid
        ),
        confidence=sum(adopted_conf) / len(adopted_conf) if adopted_conf else 0.6,
        intent_type=intent_type,
        require_light=require_light,
        max_spice=max_spice,
        max_minutes=max_minutes,
        prefer_fridge=prefer_fridge,
        avoid_meat=avoid_meat,
        cuisine=cuisine,
        category=category,
        avoid=rule.avoid,
    )
