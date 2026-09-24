"""一句话理由生成 (需求 6)

结果卡上的那句话是「饭决」建立信任的关键: 用户凭什么信一个随手点出来的答案?
答案必须**具体到这个人**, 而不是"营养丰富、美味可口"这种谁都能说的话。

为什么是纯规则而不是 LLM:
1. LLM 要 1-3 秒, 而决策的目标是 2 秒内出结果 —— 理由不能是瓶颈
2. 断网时必须也能出理由 (需求 7), LLM 做不到
3. 规则可测: 每条理由都能写单测断言, LLM 的输出只能靠祈祷

规则按优先级从上往下, 返回第一条命中的。顺序是有讲究的:
「3 天没吃辣」这种从用户**自己的历史**里来的, 比「家里有一半食材」这种只看冰箱的
事实更私人, 更私人 = 更像真的懂用户 = 更应该说。

⚠️ 不许为"凑一句话"而加规则: 全部规则都不命中时返回**空字符串**, 不兜万能句。
这里曾经兜过「今天这个，不亏。」—— 它对每一道菜都成立, 说了等于没说, 还让用户以为
App 真的看出了什么。万能句比没有更假: 没有最多是"这次没话说", 万能句是假的懂。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings

# 候选池被去重规则榨干时的说法 —— 必须诚实, 不要假装规则生效了
FALLBACK_REASON = "可选项不多了，就它吧。"


@dataclass
class ReasonContext:
    """生成理由所需的事实。全部可选: 缺哪个就跳过哪条规则。"""

    # 菜名。只用于在同一条规则里挑说法变体 (同一道菜永远同一句话)
    dish: Optional[str] = None
    # 距上一次吃到辣味菜的天数 (None = 没数据)
    days_since_spicy: Optional[int] = None
    # 距上一次吃这道菜的天数
    days_since_dish: Optional[int] = None
    # 命中的临期食材名
    expiring_item: Optional[str] = None
    # 天气条件: rain / snow / hot / cold / sunny / cloudy
    weather: Optional[str] = None
    # 餐次槽位
    meal_slot: Optional[str] = None
    # 换了个菜系 (本次与上一餐不同)。注意: cuisine 列现在是脏的, 常常是分类词
    # 而不是菜系, 轮换规则会自行判断 (见 _GENERIC_CUISINE_LABELS)
    cuisine: Optional[str] = None
    cuisine_rotated: bool = False
    # 家里现有食材的命中比例 0-1
    inventory_ratio: float = 0.0
    # 去重规则被放宽了 (候选不够, 只能放宽)
    relaxed: bool = False


@dataclass
class ReasonRule:
    """一条理由规则

    template 里可以带 {n} / {item} / {cuisine} / {pct} 占位符。
    """

    name: str
    template: str
    # 返回 True 表示命中。注意: 命中时模板里的占位符必须都能填出来,
    # 否则会生成"你 {n} 天没吃辣了"这种鬼话 —— 所以每条规则自己保证数据齐全。
    matches: object = field(default=None)


def _int(value: Optional[int]) -> int:
    return int(value or 0)


# 同义说法池。
# 「换换口味，试试X」和「深夜吃点轻的，负担小」这两条命中率很高 —— 没库存、
# 没天气、没历史的时候几乎次次都落到它们身上。连点三次看到同一句模板,
# 用户就会觉得"这 App 就一句话", 理由建立信任的作用反而没了。
# 所以给高频规则准备几种说法, 按菜名取模挑一种: 同一道菜永远同一句(可复现),
# 不同菜换不同说法(不重样)。
_LATE_NIGHT_LINES = (
    "深夜吃点轻的，负担小",
    "夜宵别太重，这个刚好",
    "睡前吃这个，不撑",
)
_ROTATION_TEMPLATES = (
    "换换口味，试试{cuisine}",
    "{cuisine}好久没吃了",
    "来点{cuisine}，换个节奏",
)

# 这些不是菜系, 是菜品分类。recipe.cuisine 列历史上存的就是分类(荤菜/主食/早餐…),
# 直接套进轮换模板会生成「换换口味，试试早餐」「来点半成品加工，换个节奏」这种话 ——
# 句子是通的, 但摆在结果卡上很荒谬, 用户一眼就看出 App 不懂自己在说什么。
# 所以命中这些值时整条轮换规则跳过, 退回后面的规则; 后面也不命中就返回空(不兜底)。
#
# 本期不做 cuisine 列清洗: 真菜系由凌晨 LLM 富集任务标注回填。
# 回填完成后 recipe.cuisine 只会出现真菜系, 这张表连同命中逻辑可以一起删掉。
# ⚠️ 同一张表在 shared/decide.ts 的 GENERIC_CUISINE_LABELS 有一份副本(shared 是唯一真源),
# 改这里必须同步改那边, 否则用户联网和断网看到的话术不一样。
# 词表取自 recipe.cuisine 的实际取值(含「调料」「半成品」这两个源站口径, 见
# output/non-dish-candidates-2026-09-23.csv), 不是拍脑袋列的。
_GENERIC_CUISINE_LABELS = frozenset(
    {
        "荤菜", "素菜", "主食", "面食", "汤羹", "汤与粥", "凉菜",
        "小吃", "早餐", "饮品", "甜品", "半成品加工", "调味品", "水产",
        "调料", "半成品",
    }
)


def _variant(pool, key: Optional[str]) -> str:
    """按菜名稳定地挑一种说法 —— 不用 random, 否则同一道菜两次说法不同会很假"""
    if not pool:
        return ""
    seed = sum(ord(ch) for ch in (key or ""))
    return pool[seed % len(pool)]


class ReasonService:
    """按优先级产出一句话理由"""

    def __init__(self) -> None:
        self.settings = get_settings().decide

    def build(self, ctx: ReasonContext, max_chars: Optional[int] = None) -> str:
        limit = max_chars if max_chars is not None else self.settings.reason_max_chars

        if ctx.relaxed:
            return self._clip(FALLBACK_REASON, limit)

        for text in self._candidates(ctx):
            if text:
                return self._clip(text, limit)
        # 一条都没命中就说实话: 没有。不兜「今天这个，不亏。」这类万能句 ——
        # 它对每道菜都成立, 摆在这儿只会让人以为 App 看出了什么(见文件头)。
        return ""

    def _candidates(self, ctx: ReasonContext) -> list[Optional[str]]:
        late_night = ctx.meal_slot == "late_night"
        return [
            self._rule_spicy(ctx),
            self._rule_expiring(ctx),
            self._rule_weather(ctx),
            self._rule_late_night(ctx) if late_night else None,
            self._rule_long_absent(ctx),
            self._rule_rotation(ctx),
            self._rule_inventory(ctx),
        ]

    # --- 具体规则 ---

    def _rule_spicy(self, ctx: ReasonContext) -> Optional[str]:
        days = ctx.days_since_spicy
        if days is None or days < 3:
            return None
        # 中文数字读起来更自然: "你 5 天没吃辣了" 比 "你已经五天没吃辣了" 短
        return f"你 {_int(days)} 天没吃辣了"

    def _rule_expiring(self, ctx: ReasonContext) -> Optional[str]:
        if not ctx.expiring_item:
            return None
        item = ctx.expiring_item
        # 素材名可能很长, 超了就砍到 4 个字
        if len(item) > 4:
            item = item[:4]
        return f"冰箱的{item}快到期了"

    def _rule_weather(self, ctx: ReasonContext) -> Optional[str]:
        if ctx.weather == "rain":
            return "外面下雨，在家煮锅暖的"
        if ctx.weather == "snow":
            return "下雪天，来点热乎的"
        if ctx.weather == "hot":
            return "天热，吃点清爽的"
        if ctx.weather == "cold":
            return "天冷，喝口热的"
        return None

    def _rule_late_night(self, ctx: ReasonContext) -> Optional[str]:
        return _variant(_LATE_NIGHT_LINES, ctx.dish)

    def _rule_long_absent(self, ctx: ReasonContext) -> Optional[str]:
        days = ctx.days_since_dish
        if days is None or days < 6:
            return None
        return f"这道菜 {_int(days)} 天没上桌了"

    def _rule_rotation(self, ctx: ReasonContext) -> Optional[str]:
        if not ctx.cuisine_rotated or not ctx.cuisine:
            return None
        # 分类词不是菜系, 说出来那句话是废话 (见 _GENERIC_CUISINE_LABELS 的说明)
        if ctx.cuisine in _GENERIC_CUISINE_LABELS:
            return None
        return _variant(_ROTATION_TEMPLATES, ctx.dish).format(cuisine=ctx.cuisine)

    # ⚠️ 这里曾经有一条「{n} 分钟搞定，不误事」(_rule_quick), 2026-09-23 整条摘掉:
    # cook_minutes 是规则回填的品类基准值不是实测(全库 119 道菜都是 22 = 荤菜默认值),
    # 拿它说"20 分钟搞定"是**假精确** —— 用户照着安排今晚, 结果不是。
    # 时间维度只留在引擎内部(出餐上限 / 深夜阈值), 对外只给结果卡上的档位词
    # (见 DecideBoard.tsx 的注释)。别把它加回来。

    def _rule_inventory(self, ctx: ReasonContext) -> Optional[str]:
        if ctx.inventory_ratio < 0.5:
            return None
        # "家里有 7 成食材" 太绕, 说人话就是"家里现成就有"
        if ctx.inventory_ratio >= 0.8:
            return "家里现成就有，别买了"
        return "家里有一半食材，顺手"

    # --- 收尾 ---

    def _clip(self, text: str, limit: int) -> str:
        """硬裁剪到字数上限。规则本身应该写短, 这里只是兜底, 宁可断也不能超。"""
        if limit <= 0 or len(text) <= limit:
            return text
        return text[:limit]
