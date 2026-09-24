"""菜品场景字段的规则推断 —— 脚本与服务共用同一份

为什么单独抽出来:
    回填脚本(scripts/backfill_dish_scene_fields.py)和富集服务都要用这些规则。放两处
    必然漂移 —— 脚本补的和服务补的口径不一致, 数据就分成两批, 事后根本查不清。

    规则推断的定位是**先填个大概**: 它不调模型、不联网、可重复跑, 用来把 93% 缺失
    的 cook_minutes 之类的洞先堵上。LLM 之后再精修, 但规则填错的成本远低于空着
    —— 空着意味着决策引擎里 `cook_minutes or 30` 永远生效, 硬规则全废。

保守原则:
    判断不了就返回 None(不限制), 而不是塞默认值。meal_slots 空 = 不限制餐次,
    meat_type 空 = 不知道荤素。宁可让规则不生效, 也不要生效成错的。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func

from app.models.recipe import CookTool, DishSeason, MeatType, Recipe

# ---- 耗时 ----

# 品类 → 基准耗时, 取同类家常菜中位数, 略偏保守(估短了会把慢菜推给赶时间的人)
CATEGORY_MINUTES: Dict[str, int] = {
    "凉菜": 10, "素菜": 12, "主食": 25, "面食": 20,
    "荤菜": 22, "小吃": 25, "汤羹": 40,
}

# 做法关键词 → 耗时, 优先级高于品类基准
METHOD_MINUTES: Sequence[tuple] = (
    (("煲", "炖", "煨", "卤", "焖"), 60),
    (("烤", "焗", "炸"), 40),
    (("蒸",), 25),
    (("煮", "汆", "涮"), 20),
    (("炒", "爆", "熘", "煸", "煎"), 15),
    (("拌", "拍", "腌"), 10),
)

# 中文数字也要认: 「十分钟快手菜」是很常见的写法, 只认阿拉伯数字会漏掉一大片
CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
EXPLICIT_MINUTES_RE = re.compile(r"([0-9]{1,3}|[一二两三四五六七八九十]{1,3})\s*分钟")


def _parse_minutes_token(token: str) -> Optional[int]:
    """解析「20」「二十」「十」这几种写法"""
    if token.isdigit():
        return int(token)
    if token in CN_DIGITS:
        return CN_DIGITS[token]
    if len(token) == 2 and token[0] == "十" and token[1] in CN_DIGITS:
        return 10 + CN_DIGITS[token[1]]
    if len(token) == 2 and token[0] in CN_DIGITS and token[1] == "十":
        return CN_DIGITS[token[0]] * 10
    if len(token) == 3 and token[0] in CN_DIGITS and token[1] == "十" and token[2] in CN_DIGITS:
        return CN_DIGITS[token[0]] * 10 + CN_DIGITS[token[2]]
    return None

# ---- 荤型 ----

SEAFOOD_WORDS = ("鱼", "虾", "蟹", "贝", "蛤", "蚝", "鱿", "鳝", "带子")
POULTRY_WORDS = ("鸡", "鸭", "鹅", "鸽", "鹌鹑")
# 「肉」单字只在这里兜底: 鱼/鸡/鸭都已在前面判走, 剩下的"肉丝/肉末/肉片"默认是猪。
RED_MEAT_WORDS = ("猪", "牛", "羊", "排骨", "五花", "里脊", "火腿", "培根", "香肠", "腊", "肉")

# 抠掉假阳性词再判。「鱼香肉丝」没有鱼, 「鸡精」不是鸡肉, 「牛奶」不是牛肉 ——
# 这三个坑和 recipe_field_rules 里遇到的是同一类, 不抠掉用户说"吃素"就吃不上饭。
SEAFOOD_FALSE = ("鱼香", "鱼露", "虾皮", "虾米", "海鲜酱", "鱼豆腐")
POULTRY_FALSE = ("鸡精", "鸡粉", "鸡汁", "鸡蛋", "鸭蛋", "鸡毛菜")
RED_FALSE = ("牛肉末", "牛奶", "牛油", "牛轧")

EGG_DAIRY_WORDS = ("鸡蛋", "鸭蛋", "鹅蛋", "牛奶", "芝士", "奶酪")
VEGETARIAN_WORDS = ("素", "斋", "清炒", "白灼", "蒜蓉", "凉拌", "干煸")

# ---- 是否是一道菜 ----

# 源分类黑名单。导入时列错位, recipe.cuisine 装的是源分类而不是菜系: 这些分类里的
# 条目从来就不是"一道菜"。字段清洗成真菜系后这张表会失效 —— 那正是下面那份
# NON_DISH_NAMES 存在的理由: 事故清单被固化下来了, 不依赖任何会被清洗的列。
#
# 「半成品加工 / 半成品」**不在**这张表里。它们描述的是加工程度而不是"是不是一道菜"
# —— 速冻水饺、炸薯条、空气炸锅鸡翅中确实是一顿饭, 只是做起来省事。把这类摘出去
# 是要付代价的: 夜宵轻食池只有 16 道, 每少一道都在推高候选枯竭率。
# 这一档里真正该拦的是蹭进来的调味品/甜品(牛油火锅底料、懒人蛋挞), 它们由下面
# 的原名表与后缀表精确拦住, 不需要扩大到整个分类。
NON_DISH_SOURCE_CATEGORIES = frozenset({
    "调味品", "调料", "饮品", "甜品",
})

# 2026-09-23 事故清单里那 54 条的原名。逐条人工核过(并经数据侧复核拧回了 C 档 8 道),
# 不删不改写半个字符 —— 它是唯一一份不依赖 cuisine 的证据, 将来即便源数据全部清洗过
# 也能原样复现。
NON_DISH_NAMES = frozenset({
    "B52轰炸机", "Mojito莫吉托", "冬瓜茶", "冰粉", "印度奶茶",
    "反沙芋头", "可乐桶", "咖啡椰奶冻", "奇异果菠菜特调", "奥利奥冰淇淋", "奶茶",
    "懒人蛋挞", "戚风蛋糕", "提拉米苏", "无厨师机蜂蜜面包", "杨枝甘露", "柠檬水",
    "油泼辣子", "油酥", "泰国手标红茶", "海边落日", "炸串酱料", "炸鲜奶",
    "烤箱版巴斯克芝士蛋糕", "烤蛋挞", "牛油果拉西", "牛油火锅底料", "玛格丽特饼干",
    "百香果橙子特调", "砂糖椰子冰沙", "简易版炒糖色",
    "糖醋汁", "番茄红酱", "红柚蛋糕", "耙耙柑茶", "胡萝卜甜糕", "芋泥雪媚娘", "英式司康",
    "草莓冰淇淋", "草莓酱", "菠萝咖啡特调", "葱油", "蒜香酱油", "蔗糖糖浆",
    "酒酿醪糟", "酸奶意式奶冻", "酸梅汤", "酸梅汤（半成品加工）",
    "金汤力", "金菲士", "长岛冰茶", "雪花酥", "魔芋蛋糕", "龟苓膏",
})

# 结尾即定性。为什么不用「酱/油/汁/汤/酥」这种更短的后缀: 酱牛肉、葱油拌面、
# 醪糟小汤圆、小酥肉全是正经菜, 按短后缀判会直接把它们从候选池里抹掉。
# 这里的每一个后缀都在现有 396 条上跑过, 确认除目标项外无命中。
NON_DISH_SUFFIXES: Sequence[str] = (
    # 甜品
    "冰淇淋", "雪媚娘", "雪花酥", "奶冻", "司康", "饼干", "蛋挞", "布丁",
    # 饮品
    "奶茶", "柠檬水", "气泡水", "苏打水", "奶昔", "果昔", "冰沙", "冰茶", "冰粉",
    # 调味品
    "酱料", "辣子", "底料", "糖色", "糖浆",
)

# 出现在菜名任意位置即定性。同样是宁缺毋滥: 「半成品」原在这一档, 后来跟着
# C 档一起摘掉了 —— 半成品意面、速冻水饺都还是一顿饭。留下来的这几个词在现有
# 396 条上跑过, 确认除目标项外无命中。
NON_DISH_WORDS: Sequence[str] = (
    "莫吉托", "鸡尾酒", "轰炸机", "汤力", "菲士", "拉西",
    "酸梅汤", "啤酒桶", "可乐桶",
)


def guess_is_dish(recipe) -> bool:
    """判「是不是一道菜」。判不了就返回 True —— 放行

    默认放行而不是默认拦: 一道正常的菜被错杀, 用户永远推不到它, 而且没人会察觉;
    反过来漏判一道奶茶, 最坏是用户多翻一次白眼。两条路的成本不对称。

    三层判定, 从"最确定"到"最兜底":
        1. 源分类黑名单 —— 覆盖当前全部问题数据
        2. 事故清单原名 —— cuisine 将来被清洗成真菜系后, 靠这一层兜住同一批条目
        3. 后缀 / 关键词 —— 接住那些 cuisine 为 NULL(如 ai_generated)的同类型条目
    """
    name = (getattr(recipe, "name", None) or "").strip()
    if not name:
        return True
    cuisine = (getattr(recipe, "cuisine", None) or "").strip()
    if cuisine in NON_DISH_SOURCE_CATEGORIES:
        return False
    if name in NON_DISH_NAMES:
        return False
    lowered = name.lower()
    if name.endswith(NON_DISH_SUFFIXES):
        return False
    return not any(word.lower() in lowered for word in NON_DISH_WORDS)


def is_dish_flag(value: Optional[bool]) -> bool:
    """把列值/离线池里的取值变成可直接用于过滤的布尔, NULL/未知一律 True

    离线候选池是不带 is_dish 字段的短键数据, 走到这里时入参就是 None。缺失按
    '是一道菜'处理 —— 缺字段不该让用户没得吃。
    """
    if value is None:
        return True
    return bool(value)


def dish_only():
    """候选加载的统一闸门 —— 决策主链路和三条旁路都只认这一个表达式

    为什么抽成一个函数: 换一道菜 / 冰箱荐菜 / 周菜单生成各 SELECT 一次 recipe,
    四条 SQL 各写一遍 is_dish 条件, 必然会在某次改动里漏掉一条 —— 而漏掉的那条
    恰恰最难复现: 用户只在点「换一个」时才会看到油泼辣子。

    COALESCE 而不是 `is_dish == 1`: 万一某行的值是 NULL, 宁可放行也不要让用户没菜吃。
    """
    return func.coalesce(Recipe.is_dish, 1) == 1


# ---- 餐次 / 厨具 / 时令 ----

BREAKFAST_WORDS = ("粥", "馒头", "豆浆", "油条", "煎蛋", "三明治", "燕麦")
LATE_NIGHT_WORDS = ("夜宵", "烧烤", "小龙虾", "炒饭", "泡面")


def haystack_of(recipe) -> str:
    """菜名 + 所有食材名 —— 判荤素的最小可信文本"""
    parts = [recipe.name or ""]
    for ri in getattr(recipe, "recipe_ingredients", None) or []:
        if getattr(ri, "ingredient", None):
            parts.append(ri.ingredient.name or "")
    return " ".join(parts)


def _strip(text: str, words: Sequence[str]) -> str:
    out = text or ""
    for word in words:
        out = out.replace(word, "")
    return out


def guess_minutes(recipe) -> Optional[int]:
    """估烹饪时间。菜名里写了算最准, 其次看做法, 最后看品类"""
    name = recipe.name or ""
    hit = EXPLICIT_MINUTES_RE.search(name)
    if hit:
        value = _parse_minutes_token(hit.group(1))
        if value and 3 <= value <= 240:
            return value
    for words, minutes in METHOD_MINUTES:
        if any(w in name for w in words):
            return minutes
    return CATEGORY_MINUTES.get(getattr(recipe, "category", None) or "")


def guess_meat_type(recipe) -> Optional[str]:
    """判荤型。判不了返回 None, 绝不默认成"素" —— 默认素会让忌口用户吃到肉

    判定顺序有讲究, 不能随便换:
        水产 → 禽 → 红肉 → 蛋奶 → 素
    把「肉」这个兜底字放在红肉那一档、且排在禽之后, 是因为"鸡肉/鸭肉"必须先被禽接走;
    反过来先把"鱼"抠掉假阳性(鱼香肉丝没有鱼)再判, 否则素菜会被判成水产。
    """
    hay = haystack_of(recipe)
    if any(w in _strip(hay, SEAFOOD_FALSE) for w in SEAFOOD_WORDS):
        return MeatType.SEAFOOD
    if any(w in _strip(hay, POULTRY_FALSE) for w in POULTRY_WORDS):
        return MeatType.POULTRY
    if any(w in _strip(hay, RED_FALSE) for w in RED_MEAT_WORDS):
        return MeatType.RED_MEAT
    if any(w in hay for w in EGG_DAIRY_WORDS):
        return MeatType.EGG_DAIRY
    if any(w in hay for w in VEGETARIAN_WORDS):
        return MeatType.NONE
    return None


def guess_meal_slots(recipe) -> Optional[List[str]]:
    """判适合餐次。判不了返回 None(不限制), 而不是塞个默认值"""
    name = recipe.name or ""
    slots: List[str] = []
    if any(w in name for w in BREAKFAST_WORDS) and "炒" not in name:
        slots.append("breakfast")
    if any(w in name for w in LATE_NIGHT_WORDS):
        slots.append("late_night")
    if getattr(recipe, "category", None) == "汤羹":
        slots.append("dinner")
    if not slots:
        return None
    # 早餐菜中午吃也没问题, 反过来不行, 所以早餐 → 早+午
    if "breakfast" in slots:
        return ["breakfast", "lunch"]
    return sorted(set(slots + ["dinner"]))


def guess_tools(recipe) -> Optional[List[str]]:
    """判所需厨具。炒锅是默认, 不写; 只记"没有就做不了"的那些"""
    name = recipe.name or ""
    tools: List[str] = []
    if "蒸" in name:
        tools.append(CookTool.STEAMER)
    if "烤" in name or "焗" in name:
        tools.append(CookTool.OVEN)
    if "空气炸" in name:
        tools.append(CookTool.AIR_FRYER)
    if "煲" in name or "炖" in name:
        tools.append(CookTool.POT)
    return sorted(set(tools)) or None


def guess_season(recipe) -> Optional[List[str]]:
    """时令。绝大多数菜四季皆可, 只认最典型的几个"""
    name = recipe.name or ""
    if any(w in name for w in ("冬瓜", "绿豆", "苦瓜", "凉拌")):
        return [DishSeason.SUMMER]
    if any(w in name for w in ("萝卜", "火锅", "煲")):
        return [DishSeason.WINTER]
    return None


def to_json(values: Optional[List[str]]) -> Optional[str]:
    return json.dumps(values, ensure_ascii=False) if values else None
