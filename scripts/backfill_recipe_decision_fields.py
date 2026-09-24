#!/usr/bin/env python3
"""回填存量菜谱的「饭决」决策字段

背景
    迁移 0014_fan_decide 只给 recipe 加了列, 没有回灌数据 —— 存量几百道菜的
    category / main_ingredient / tags / flavor_tags / spice_level / is_light /
    cover_text / quick_steps 全是空的。这会让决策引擎的两条硬规则退化:
      - 「同品类打散」  依赖 category, 空值等于不打散
      - 「连续两餐不重样」依赖 main_ingredient, 空值等于不判重
    结果卡角标(cover_text)与极简做法(quick_steps)也会是空的。

做法
    纯规则推断, 不调 LLM —— 离线可跑、可重复执行、结果可预测。
    规则口径与 data/local_dish_pool.json 保持一致(同样的品类枚举、标签词表、
    辣度 0-4、步骤 <=20 字), 这样服务端菜谱与离线候选池的决策表现一致。

幂等性
    只处理「待回填」的菜谱(上面那些可空字段里还有空的), 已填满的不再触碰,
    因此可以随时中断重跑。 spice_level / is_light 有默认值(0 / False), 无法区分
    「没填」和「填了 0」, 所以这两个只在菜谱仍在待回填集合里时才写入。
    规则调优后想整体重算: 加 --force。

用法
    python scripts/backfill_recipe_decision_fields.py --dry-run        # 只看不写
    python scripts/backfill_recipe_decision_fields.py --dry-run --preview 30
    python scripts/backfill_recipe_decision_fields.py --limit 20       # 小批量试
    python scripts/backfill_recipe_decision_fields.py                  # 正式回填
    python scripts/backfill_recipe_decision_fields.py --force          # 全量重算
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for _path in (str(ROOT), str(BACKEND)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.config import get_settings  # noqa: E402
from app.database import async_session_factory, close_db  # noqa: E402
from app.models.recipe import Recipe  # noqa: E402
from sqlalchemy import or_, select  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill-decide-fields")

# --------------------------------------------------------------------------- 词表

# 品类枚举必须与迁移 0014 的注释、local_dish_pool.json 一致
CATEGORIES = ("荤菜", "素菜", "汤羹", "主食", "面食", "凉菜", "小吃")

# 场景标签词表(与 local_dish_pool.json 一致, 外加「炖煮」)
TAG_VOCAB = ("快手", "一锅出", "下饭", "汤羹", "轻食", "夜宵", "雨天", "热辣", "清爽", "炖煮")
# 味型标签词表
FLAVOR_VOCAB = ("辣", "酸", "甜", "咸鲜", "酱香")

# 调味品/辅料: 永远不当主料, 也不参与「有没有肉」的判断
# (鸡精含「鸡」、蚝油含「蚝」, 不过滤的话会被误判成荤菜)
SEASONING_EXACT = {
    "盐", "食盐", "油", "食用油", "菜籽油", "橄榄油", "香油", "芝麻油", "花椒油", "辣椒油",
    "生抽", "老抽", "酱油", "蒸鱼豉油", "豉油", "蚝油", "鱼露",
    "醋", "香醋", "白醋", "米醋", "陈醋", "柠檬汁",
    "糖", "白糖", "白砂糖", "冰糖", "红糖", "蜂蜜", "味精", "鸡精",
    "淀粉", "生粉", "水淀粉", "料酒", "黄酒", "白酒", "啤酒", "清水", "水", "冰水", "高汤",
    "姜", "生姜", "蒜", "大蒜", "葱", "小葱", "大葱", "香葱",
    "八角", "桂皮", "香叶", "草果", "花椒", "麻椒", "藤椒", "孜然", "五香粉", "十三香",
    "干辣椒", "辣椒", "小米辣", "朝天椒", "剁椒", "泡椒", "辣椒酱", "豆瓣酱", "甜面酱",
    "番茄酱", "沙拉酱", "芝麻酱", "柱侯酱", "沙茶酱", "芥末", "咖喱粉",
    "胡椒粉", "白胡椒粉", "黑胡椒", "胡椒", "花椒粉", "辣椒粉", "孜然粉",
    "酵母", "泡打粉", "小苏打", "碱面",
}
# 这些是「包含即调味品」: 名字里带这些字的一律不可能是主料
SEASONING_CONTAINS = ("酱", "精", "椒", "料粉", "调味")

# 辣度信号, 由强到弱
STRONG_CHILI = ("小米辣", "朝天椒", "魔鬼椒", "辣椒酱", "剁椒", "泡椒", "麻辣", "爆辣",
                "特辣", "变态辣", "辣子", "水煮", "干锅", "火鸡")
MEDIUM_CHILI = ("干辣椒", "辣椒", "豆瓣酱", "麻椒", "藤椒", "香辣", "酸辣", "辣白菜")
MILD_CHILI = ("花椒", "胡椒", "咖喱", "孜然")

# 味型信号
SOUR_HINTS = ("醋", "柠檬", "酸菜", "泡菜", "山楂", "酸梅", "杨梅", "番茄酱")
SWEET_HINTS = ("糖", "冰糖", "蜂蜜", "可乐", "蜜", "红枣", "甜面酱", "炼乳", "枣")
UMAMI_HINTS = ("生抽", "老抽", "酱油", "蚝油", "蒸鱼豉油", "豉油", "鸡精", "味精", "盐")
SAUCE_HINTS = ("豆瓣酱", "甜面酱", "豆豉", "柱侯酱", "沙茶", "芝麻酱", "麻酱", "酱香", "豉油")

# 主食 / 面食信号
NOODLE_HINTS = ("面", "米线", "米粉", "河粉", "宽粉", "粉丝", "粉条", "乌冬", "意面", "拉面")
STAPLE_HINTS = ("饭", "粥", "米饭", "大米", "糯米", "小米", "馒头", "包子", "饺子",
                "馄饨", "饼", "粽", "窝头")
SOUP_HINTS = ("汤", "羹")
COLD_HINTS = ("拌", "凉拌", "拍黄瓜", "泡菜", "卤", "冻", "沙拉")
SNACK_HINTS = ("炸", "丸子", "串", "酥", "点心", "布丁", "薯条", "桃酥")

# 荤食信号(用于品类判断)
MEAT_HINTS = ("牛", "羊", "猪", "肉", "鸡", "鸭", "鹅", "排骨", "蹄", "肝", "肚", "腰",
              "培根", "火腿", "腊肠", "腊肉", "香肠", "培根", "鸭血", "毛肚", "血",
              # 水产与蛋同样算荤: 清蒸鲈鱼、番茄炒蛋都是荤菜
              "鱼", "虾", "蟹", "贝", "蛤", "鱿", "鲍", "参", "蚝", "鳝", "鳕",
              "墨鱼", "章鱼", "海鲜", "蛋")
# 这些只是「配料级」的肉: 麻婆豆腐里的肉末不该让整道菜变成荤菜
MINOR_MEAT = ("肉末", "肉丝", "肉片", "肉松", "肉臊", "肉馅")

# 饮品信号: 存量库里混进了酒水/茶饮, 它们不该参与决策, 回填时单独报出来
DRINK_HINTS = ("鸡尾", "莫吉托", "伏特加", "威士忌", "朗姆", "啤酒", "白酒", "红酒",
               "气泡水", "奶昔", "果汁", "汽水", "冬瓜茶", "柠檬水", "酸梅汤")

# 主料候选, 按顺序优先: 水产 > 肉禽 > 蛋豆 > 主食 > 菌菇蔬菜 > 其他
MAIN_GROUPS: Sequence[tuple] = (
    ("水产", ("虾", "鱼", "蟹", "贝", "蛤", "鱿", "鲍", "参", "蚝", "鳝", "鳕", "墨鱼", "章鱼")),
    ("肉禽", ("牛", "羊", "猪", "肉", "鸡", "鸭", "鹅", "排骨", "蹄", "肝", "肚", "腰",
              "培根", "火腿", "腊", "香肠", "鸭血", "毛肚")),
    ("蛋豆", ("鸡蛋", "蛋", "豆腐", "豆干", "香干", "腐竹", "豆皮", "千张")),
    ("主食", ("面条", "挂面", "拉面", "手擀面", "细面", "面", "米线", "米粉", "河粉",
              "粉丝", "粉条", "米饭", "大米", "糯米", "面粉", "饺子", "包子", "馒头",
              "饼", "粥")),
)

# 主料归一化: 让「牛腩」和「牛里脊」都算牛肉, 这样「连续两餐不重样」才真的生效
MAIN_ALIAS = {
    "牛": "牛肉", "羊": "羊肉", "猪肉": "猪肉", "瘦肉": "猪肉", "里脊肉": "猪肉",
    "肉末": "猪肉", "肉丝": "猪肉", "肉片": "猪肉", "五花肉": "五花肉",
    "排骨": "排骨", "肋排": "排骨", "大排": "排骨", "猪蹄": "猪蹄",
    "鸡胸肉": "鸡胸肉", "鸡腿肉": "鸡腿肉", "鸡翅": "鸡翅", "鸡腿": "鸡腿",
    "鸡爪": "鸡爪", "鸡肉": "鸡肉", "三黄鸡": "鸡肉", "整鸡": "鸡肉",
    "虾仁": "虾仁", "基围虾": "虾仁", "虾": "虾仁",
    "鸡蛋": "鸡蛋", "鸭蛋": "鸡蛋", "鹌鹑蛋": "鸡蛋", "咸蛋": "鸡蛋",
    "豆腐": "豆腐", "嫩豆腐": "豆腐", "老豆腐": "豆腐", "北豆腐": "豆腐", "南豆腐": "豆腐",
    "豆干": "豆干", "香干": "豆干",
    "面条": "面条", "挂面": "面条", "拉面": "面条", "手擀面": "面条", "细面": "面条",
    "米饭": "米饭", "大米": "米饭", "糯米": "米饭", "隔夜米饭": "米饭",
    "米线": "米线", "米粉": "米线", "河粉": "米线",
    # 菜名/食材里只写了一个字的情况, 补足成完整主料名
    "肉": "猪肉", "鸡": "鸡肉", "鸭": "鸭肉", "鹅": "鹅肉",
    "面": "面条", "饭": "米饭", "羊排": "羊肉", "牛腩": "牛肉", "牛里脊": "牛肉",
    # 蔬菜类的别名收一收, 否则「大白菜嫩叶」和「白菜」会被当成两条不同的主料
    "大白菜": "白菜", "大白菜嫩叶": "白菜", "小白菜": "白菜", "圆白菜": "白菜",
    "娃娃菜": "娃娃菜", "西蓝花": "西蓝花", "西兰花": "西蓝花",
}

# 轻食 / 重口信号(深夜只从轻食里挑, 判错比不判更糟, 所以两边都从严)
HEAVY_HINTS = ("炸", "红烧", "糖醋", "油焖", "干锅", "麻辣", "火锅", "回锅", "肥肠",
               "五花", "猪蹄", "扣肉", "肘子", "烧烤", "爆炒")
LIGHT_HINTS = ("清蒸", "白灼", "凉拌", "沙拉", "清炒", "蒜蓉", "水焯", "汆", "上汤", "清炖")

_STEP_SPLIT = re.compile(r"[，,。；;\n\r]+")
_STEP_PREFIX = re.compile(r"^\s*[0-9０-９]+[.、)）:：]\s*")

MAX_STEP_LEN = 20
MAX_QUICK_STEPS = 5


# --------------------------------------------------------------------------- 纯规则函数

def _norm(text: Optional[str]) -> str:
    return (text or "").strip()


def is_seasoning(name: str) -> bool:
    """调味品/辅料判定 —— 它们永远不是主料, 也不代表「这道菜是荤的」"""
    n = _norm(name)
    if not n or n in SEASONING_EXACT:
        return True
    return any(k in n for k in SEASONING_CONTAINS)


def split_raw_steps(steps_text: Optional[str]) -> List[str]:
    """老菜谱的 steps 是一整段文本(逗号或换行分隔), 拆成独立步骤"""
    raw = _norm(steps_text)
    if not raw:
        return []
    return [s for s in (_STEP_PREFIX.sub("", part).strip() for part in _STEP_SPLIT.split(raw)) if s]


def build_quick_steps(steps_text: Optional[str]) -> List[str]:
    """极简做法: 3-5 步, 每步 <=20 字"""
    parts = split_raw_steps(steps_text)
    if not parts:
        return []
    out: List[str] = []
    for part in parts[:MAX_QUICK_STEPS]:
        if len(part) > MAX_STEP_LEN:
            part = part[: MAX_STEP_LEN - 1].rstrip("，,。;；") + "…"
        out.append(part)
    return out


def infer_category(name: str, ingredients: Sequence[str], steps_text: Optional[str] = None) -> str:
    """品类: 面食 > 主食 > 汤羹 > 凉菜 > 小吃 > 荤菜 > 素菜"""
    n = _norm(name)

    if any(k in n for k in NOODLE_HINTS) or any(k in ingredients for k in ("面条", "挂面", "米线", "米粉")):
        return "面食"
    if any(k in n for k in STAPLE_HINTS):
        return "主食"
    if any(k in n for k in SOUP_HINTS):
        # 「汤面/汤粉」已经在上面判成面食了, 这里剩下的是真汤羹
        return "汤羹"
    if any(k in n for k in COLD_HINTS):
        return "凉菜"
    if any(k in n for k in SNACK_HINTS):
        return "小吃"
    # 配料级的肉末/肉丝不算荤: 麻婆豆腐、干煸豆角这类素菜才不会被误判。
    # 要整条食材剔掉 —— 只抠「肉末」两个字的话, 「牛肉末」会留下「牛」又被判成荤菜。
    meat_text = n + " " + " ".join(
        i for i in ingredients
        if not any(m in i for m in MINOR_MEAT) and not any(d in i for d in DAIRY_HINTS)
    )
    for minor in MINOR_MEAT:
        meat_text = meat_text.replace(minor, "")
    if any(k in meat_text for k in MEAT_HINTS):
        return "荤菜"
    return "素菜"


GROUP_WEIGHT = {"水产": 3, "肉禽": 3, "蛋豆": 2, "主食": 2}


# 乳制品: 「牛奶」里的「牛」会让肉禽组误判, 必须先排除
DAIRY_HINTS = ("牛奶", "奶粉", "奶油", "奶酪", "酸奶", "炼乳", "牛乳", "黄油", "酥油", "芝士")


def _group_of(item: str) -> tuple:
    """食材属于哪个主料大类, 以及该大类的全部关键词"""
    if any(k in item for k in DAIRY_HINTS):
        return "", ()
    for label, keywords in MAIN_GROUPS:
        for k in keywords:
            if k in item:
                return label, keywords
    return "", ()


def _name_hit_score(name: str, item: str) -> int:
    """食材被菜名点名的程度: 全名命中 3 分, 三字片段 3 分, 两字片段 2 分

    「大白菜嫩叶」对「乾隆白菜」全称匹配不上, 但「白菜」这个两字片段是命中的。
    """
    if not item or not name:
        return 0
    if item in name:
        return 3
    for size in (3, 2):
        if len(item) < size:
            continue
        for i in range(len(item) - size + 1):
            if item[i : i + size] in name:
                return 3 if size == 3 else 2
    return 0


def infer_main_ingredient(name: str, ingredients: Sequence[str], category: str) -> str:
    """主料: 这道菜的主角, 「连续两餐不重样」的最小粒度

    用打分而不是简单的「按顺序第一个命中」:
      - 菜名里点过名的 +3, 只命中关键词(如「香菇滑鸡」里的鸡胸肉) +2
      - 大类权重: 水产/肉禽 3 > 蛋豆/主食 2 > 菌菇蔬菜 0
      - 主食类菜品再给主食 +2 (番茄鸡蛋面的主角是面条, 不是鸡蛋)
      - 配料级的肉末/肉丝 -2 (麻婆豆腐的主角是豆腐)
    """
    n = _norm(name)
    solids = [_norm(i) for i in ingredients if _norm(i) and not is_seasoning(i)]
    if not solids:
        # 没有关联食材时, 从菜名里抠: 去掉做法词, 剩下的多半是主料
        leftover = n
        for word in ("清蒸", "白灼", "红烧", "爆炒", "干煸", "水煮", "糖醋", "凉拌", "炒", "炖", "煮", "蒸", "焖"):
            leftover = leftover.replace(word, "")
        return leftover.strip()[:50] or n[:50]

    best, best_score = solids[0], -99
    for item in solids:
        label, keywords = _group_of(item)
        score = _name_hit_score(n, item)
        if score == 0:
            # 没被全称点名时再看关键词: 「香菇滑鸡」里的鸡胸肉能靠「鸡」拿到分。
            # 已经被点名的不再叠加, 否则「番茄鸡蛋面」里的鸡蛋会赢过面条。
            if any(k in n for k in keywords):
                score += 2
        score += GROUP_WEIGHT.get(label, 1)
        if label == "主食" and category in ("主食", "面食"):
            score += 2
        if any(m in item for m in MINOR_MEAT):
            score -= 2
        if score > best_score:  # 严格大于: 同分保持食材表里的先后顺序
            best, best_score = item, score
    return MAIN_ALIAS.get(best, best)[:50]


def infer_spice_level(name: str, ingredients: Sequence[str]) -> int:
    """辣度 0-4"""
    n = _norm(name)
    joined = n + " " + " ".join(ingredients)

    has_strong = any(k in joined for k in STRONG_CHILI)
    has_medium = any(k in joined for k in MEDIUM_CHILI)
    has_mild = any(k in joined for k in MILD_CHILI)

    level = 0
    if has_strong:
        level = 3
    elif has_medium:
        level = 2
    elif has_mild:
        level = 1
    if has_strong and has_medium:
        level += 1
    if has_medium and "干辣椒" in joined and "花椒" in joined:
        level += 1
    return max(0, min(4, level))


def infer_flavor_tags(ingredients: Sequence[str], spice_level: int) -> List[str]:
    """味型: 辣/酸/甜/咸鲜/酱香"""
    joined = " ".join(ingredients)
    flavors: List[str] = []
    if spice_level >= 2:
        flavors.append("辣")
    if any(k in joined for k in SOUR_HINTS):
        flavors.append("酸")
    if any(k in joined for k in SWEET_HINTS):
        flavors.append("甜")
    if any(k in joined for k in SAUCE_HINTS):
        flavors.append("酱香")
    if not flavors or any(k in joined for k in UMAMI_HINTS):
        flavors.append("咸鲜")
    # 保持词表顺序, 输出稳定
    return [f for f in FLAVOR_VOCAB if f in flavors]


def infer_is_light(name: str, category: str, calories: Optional[int],
                   minutes: Optional[int], spice_level: int) -> bool:
    """轻食: 深夜时段只从这里挑, 所以宁可判得保守"""
    n = _norm(name)
    kcal = calories or 0
    mins = minutes or 30

    if any(k in n for k in HEAVY_HINTS) or kcal >= 450 or mins >= 60:
        return False
    if any(k in n for k in LIGHT_HINTS):
        return True
    if "粥" in n and kcal <= 350:
        return True
    # 深夜只从轻食里挑, 所以素菜类从严: 低热量 + 快 + 不辣
    if category in ("素菜", "凉菜") and kcal <= 250 and mins <= 20 and spice_level <= 1:
        return True
    if category == "汤羹" and kcal <= 250:
        return True
    if category in ("主食", "面食") and kcal <= 400 and mins <= 20 and spice_level == 0:
        return True
    if category == "荤菜" and kcal <= 300 and mins <= 15 and spice_level == 0:
        return True
    return False


def infer_tags(name: str, category: str, minutes: Optional[int], calories: Optional[int],
               spice_level: int, is_light: bool) -> List[str]:
    """场景标签: 快手/一锅出/下饭/汤羹/轻食/夜宵/雨天/热辣/清爽/炖煮"""
    n = _norm(name)
    mins = minutes or 30
    kcal = calories or 0
    tags: List[str] = []

    # 面/饭/汤本身就是快手品类, 阈值比炒菜放宽一档
    quick_limit = 20 if category in ("面食", "主食", "汤羹") else 15
    if mins <= quick_limit:
        tags.append("快手")
    if mins >= 40 or any(k in n for k in ("炖", "焖", "红烧", "煲", "卤")):
        tags.append("炖煮")
    if any(k in n for k in ("煲仔饭", "炒饭", "烩饭", "盖饭", "焖饭", "火锅", "砂锅", "石锅", "乱炖")):
        tags.append("一锅出")
    if category == "汤羹":
        tags.append("汤羹")
    if (any(k in n for k in ("粥", "羹", "煲", "汤", "烩", "砂锅"))
            or "汤羹" in tags or "炖煮" in tags):
        tags.append("雨天")
    if spice_level >= 3:
        tags.append("热辣")
    if is_light:
        tags.append("轻食")
    if is_light and category in ("主食", "面食", "汤羹", "小吃"):
        tags.append("夜宵")
    if category == "凉菜" or (category == "素菜" and kcal <= 150):
        tags.append("清爽")
    if category in ("荤菜", "素菜") and "清爽" not in tags:
        tags.append("下饭")

    ordered = [t for t in TAG_VOCAB if t in tags]
    return ordered[:4]


def infer_cover_text(name: str, category: str, minutes: Optional[int], spice_level: int,
                     flavors: Sequence[str], tags: Sequence[str]) -> str:
    """结果卡角标, <=20 字"""
    mins = minutes or 30
    if spice_level >= 3:
        return "热辣"
    if mins <= 12:
        return "快手"
    if mins >= 60:
        return "硬菜"
    if "清爽" in tags:
        return "清爽"
    if "一锅出" in tags:
        return "一锅出"
    if category == "汤羹" or any(k in name for k in ("粥", "羹", "煲")):
        return "暖胃"
    if "酱香" in flavors:
        return "酱香"
    if "酸" in flavors and "甜" in flavors:
        return "酸甜"
    if "辣" in flavors:
        return "微辣"
    if category == "凉菜":
        return "开胃"
    return "下饭"


def looks_like_drink(name: str) -> bool:
    """存量库里混进了酒水/茶饮, 它们不该参与「今天吃啥」的决策, 回填时单独报出来

    「乡村啤酒鸭」这种带肉的不能算饮品 —— 啤酒只是做法词。
    """
    n = _norm(name)
    if not any(k in n for k in DRINK_HINTS):
        return False
    return not any(k in n for k in MEAT_HINTS)


def infer_all(name: str, ingredients: Sequence[str], steps_text: Optional[str] = None,
              minutes: Optional[int] = None, calories: Optional[int] = None) -> Dict[str, object]:
    """一次性算齐所有决策字段(纯函数, 不碰数据库, 方便单测)"""
    category = infer_category(name, ingredients, steps_text)
    main = infer_main_ingredient(name, ingredients, category)
    spice = infer_spice_level(name, ingredients)
    flavors = infer_flavor_tags(ingredients, spice)
    light = infer_is_light(name, category, calories, minutes, spice)
    tags = infer_tags(name, category, minutes, calories, spice, light)
    cover = infer_cover_text(name, category, minutes, spice, flavors, tags)
    return {
        "category": category,
        "main_ingredient": main,
        "spice_level": spice,
        "flavor_tags": json.dumps(flavors, ensure_ascii=False),
        "is_light": light,
        "tags": json.dumps(tags, ensure_ascii=False),
        "cover_text": cover[:20],
        "quick_steps": json.dumps(build_quick_steps(steps_text), ensure_ascii=False)
        if build_quick_steps(steps_text)
        else None,
    }


# --------------------------------------------------------------------------- 数据库回填

def _pending_filter():
    """待回填 = 任意一个可空字段还是空(已填满的不再触碰, 保证幂等)"""
    return or_(
        Recipe.category.is_(None),
        Recipe.category == "",
        Recipe.main_ingredient.is_(None),
        Recipe.main_ingredient == "",
        Recipe.cover_text.is_(None),
        Recipe.cover_text == "",
        Recipe.tags.is_(None),
        Recipe.tags == "",
        Recipe.flavor_tags.is_(None),
        Recipe.flavor_tags == "",
        Recipe.quick_steps.is_(None),
        Recipe.quick_steps == "",
    )


async def backfill(limit: Optional[int], dry_run: bool, force: bool, preview: int) -> Dict[str, int]:
    stats: Dict[str, object] = {"scanned": 0, "updated": 0, "by_category": {}, "drinks": []}
    shown = 0
    seen: set = set()

    while True:
        if limit is not None and stats["scanned"] >= limit:
            break
        size = 200 if limit is None else min(200, limit - stats["scanned"])
        async with async_session_factory() as session:
            stmt = select(Recipe).order_by(Recipe.id)
            if not force:
                stmt = stmt.where(_pending_filter())
            if seen:
                # 已处理过的不再取: dry-run 下待回填集合不会缩小, 不排除就会反复扫同一批
                stmt = stmt.where(Recipe.id.notin_(sorted(seen)))
            stmt = stmt.limit(size)
            recipes = list((await session.execute(stmt)).scalars().all())
            if not recipes:
                break

            for recipe in recipes:
                seen.add(recipe.id)
                ingredients = [
                    ri.ingredient.name
                    for ri in (recipe.recipe_ingredients or [])
                    if ri.ingredient is not None
                ]
                fields = infer_all(
                    name=recipe.name,
                    ingredients=ingredients,
                    steps_text=recipe.steps,
                    minutes=recipe.cook_minutes,
                    calories=recipe.calories,
                )
                category = str(fields["category"])
                stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
                if looks_like_drink(recipe.name):
                    stats["drinks"].append(recipe.name)

                if dry_run and shown < preview:
                    shown += 1
                    logger.info(
                        "  %-14s %-4s 主料:%-6s 辣%s 轻食:%-5s 角标:%-4s %s",
                        (recipe.name or "")[:14],
                        category,
                        str(fields["main_ingredient"])[:6],
                        fields["spice_level"],
                        "是" if fields["is_light"] else "否",
                        fields["cover_text"],
                        "/".join(json.loads(fields["tags"] or "[]")),
                    )

                if not dry_run:
                    # 只填空的; 非空说明人工改过, 不覆盖
                    if not recipe.category:
                        recipe.category = str(fields["category"])
                    if not recipe.main_ingredient:
                        recipe.main_ingredient = str(fields["main_ingredient"])
                    if not recipe.cover_text:
                        recipe.cover_text = str(fields["cover_text"])
                    if not recipe.tags:
                        recipe.tags = fields["tags"]
                    if not recipe.flavor_tags:
                        recipe.flavor_tags = fields["flavor_tags"]
                    if not recipe.quick_steps and fields["quick_steps"]:
                        recipe.quick_steps = fields["quick_steps"]
                    # 这两个有默认值, 只在首次回填时写入
                    if force or recipe.spice_level == 0:
                        recipe.spice_level = int(fields["spice_level"])
                    if force or not recipe.is_light:
                        recipe.is_light = bool(fields["is_light"])
                    stats["updated"] += 1

                stats["scanned"] += 1

            if not dry_run:
                await session.commit()

    drinks = list(dict.fromkeys(str(x) for x in stats["drinks"]))
    return {
        "scanned": stats["scanned"],
        "updated": stats["updated"],
        "by_category": stats["by_category"],
        "drinks": drinks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="回填存量菜谱的饭决决策字段")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少道 (调试用)")
    parser.add_argument("--dry-run", action="store_true", help="只推断不写入")
    parser.add_argument("--preview", type=int, default=15, help="dry-run 时打印多少条样例")
    parser.add_argument("--force", action="store_true",
                        help="全量重算(含已填好的); 规则调优后用")
    args = parser.parse_args()

    # 启动前先确认数据库配置本身是合法的, 避免拿占位密码跑一圈
    get_settings().validate_for_runtime()

    async def _run() -> Dict[str, int]:
        # close_db 必须和查询在同一个事件循环里, 否则连接池关闭时拿到的 loop 已经没了
        try:
            return await backfill(args.limit, args.dry_run, args.force, args.preview)
        finally:
            await close_db()

    result = asyncio.run(_run())

    dist = " ".join(f"{k}={v}" for k, v in sorted(result["by_category"].items(), key=lambda kv: -kv[1]))
    drinks = result.get("drinks") or []
    if args.dry_run:
        logger.info("\n预览 %s 道 (未写入): 品类分布 %s", result["scanned"], dist)
        logger.info("去掉 --dry-run 才会真正写库")
    else:
        logger.info("回填完成: %s 道, 品类分布 %s", result["updated"], dist)
    if drinks:
        logger.warning(
            "注意: 有 %s 条看起来是饮品而非菜, 建议从菜谱库剔除或加 is_drink 标记: %s",
            len(drinks), "、".join(str(x) for x in drinks[:10]) + ("…" if len(drinks) > 10 else ""),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
