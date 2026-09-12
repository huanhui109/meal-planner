"""本地演示 LLM - 不联网, 返回固定的一周菜单

用途: 本地部署 / 演示 / 前端联调。开启后整条生成链路 (落库、计价、营养、预算、
多样性、采购清单、库存扣减) 全部真实执行, 只有「模型输出」这一步是假的。
生产环境必须保持 APP__LLM__DEMO=false。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.llm.base import LLMClient

DEMO_WEEK: List[Dict[str, Any]] = [
    {
        "name": "西红柿炒鸡蛋",
        "ingredients": [("西红柿", "2个"), ("鸡蛋", "3个")],
        "calories": 320,
        "protein_g": 22.0,
        "carb_g": 18.0,
        "fat_g": 17.0,
        "cook_minutes": 15,
        "steps": "鸡蛋打散炒至凝固盛出, 西红柿炒出汁后混合, 加盐调味。",
    },
    {
        "name": "青椒土豆丝",
        "ingredients": [("土豆", "2个"), ("青椒", "2个"), ("醋", "10ml")],
        "calories": 260,
        "protein_g": 6.0,
        "carb_g": 48.0,
        "fat_g": 5.0,
        "cook_minutes": 15,
        "steps": "土豆切丝泡水去淀粉, 热油下锅大火快炒, 出锅前烹醋。",
    },
    {
        "name": "香菇滑鸡",
        "ingredients": [("鸡胸肉", "200g"), ("香菇", "4个"), ("姜", "1块")],
        "calories": 420,
        "protein_g": 44.0,
        "carb_g": 12.0,
        "fat_g": 20.0,
        "cook_minutes": 25,
        "steps": "鸡胸肉切片用淀粉抓匀, 与香菇同炒, 加姜丝去腥。",
    },
    {
        "name": "蒜蓉西蓝花",
        "ingredients": [("西蓝花", "1颗"), ("蒜", "1头")],
        "calories": 180,
        "protein_g": 10.0,
        "carb_g": 16.0,
        "fat_g": 8.0,
        "cook_minutes": 12,
        "steps": "西蓝花掰小朵焯水, 蒜末爆香后翻炒 1 分钟。",
    },
    {
        "name": "家常豆腐",
        "ingredients": [("豆腐", "1块"), ("胡萝卜", "1根"), ("酱油", "15ml")],
        "calories": 300,
        "protein_g": 20.0,
        "carb_g": 16.0,
        "fat_g": 17.0,
        "cook_minutes": 20,
        "steps": "豆腐切块两面煎黄, 加胡萝卜片与酱油小火烧 5 分钟。",
    },
    {
        "name": "洋葱炒鸡蛋",
        "ingredients": [("洋葱", "1个"), ("鸡蛋", "3个")],
        "calories": 290,
        "protein_g": 20.0,
        "carb_g": 14.0,
        "fat_g": 17.0,
        "cook_minutes": 12,
        "steps": "洋葱切丝炒软, 倒入蛋液翻炒至凝固。",
    },
    {
        "name": "清炒菠菜",
        "ingredients": [("菠菜", "1把"), ("蒜", "1头")],
        "calories": 140,
        "protein_g": 8.0,
        "carb_g": 10.0,
        "fat_g": 7.0,
        "cook_minutes": 10,
        "steps": "菠菜焯水 10 秒去草酸, 蒜末爆香后快炒。",
    },
    {
        "name": "红烧排骨",
        "ingredients": [("排骨", "500g"), ("姜", "1块"), ("白糖", "15g")],
        "calories": 640,
        "protein_g": 38.0,
        "carb_g": 18.0,
        "fat_g": 45.0,
        "cook_minutes": 45,
        "steps": "排骨焯水, 炒糖色后加姜片与热水, 小火炖 30 分钟收汁。",
    },
    {
        "name": "番茄鸡蛋面",
        "ingredients": [("面条", "150g"), ("西红柿", "2个"), ("鸡蛋", "2个")],
        "calories": 520,
        "protein_g": 24.0,
        "carb_g": 74.0,
        "fat_g": 14.0,
        "cook_minutes": 20,
        "steps": "西红柿炒出汁加水煮开, 下番茄汤底与面条, 最后淋蛋花。",
    },
    {
        "name": "木耳炒白菜",
        "ingredients": [("白菜", "1颗"), ("木耳", "30g")],
        "calories": 160,
        "protein_g": 6.0,
        "carb_g": 20.0,
        "fat_g": 6.0,
        "cook_minutes": 15,
        "steps": "木耳提前泡发, 与白菜帮先炒后下叶。",
    },
    {
        "name": "香煎鸡胸肉",
        "ingredients": [("鸡胸肉", "250g"), ("黑胡椒", "5g")],
        "calories": 380,
        "protein_g": 52.0,
        "carb_g": 3.0,
        "fat_g": 18.0,
        "cook_minutes": 18,
        "steps": "鸡胸肉拍松, 撒黑胡椒与盐腌制 10 分钟后两面煎熟。",
    },
    {
        "name": "牛奶粥",
        "ingredients": [("牛奶", "300ml"), ("大米", "80g")],
        "calories": 340,
        "protein_g": 12.0,
        "carb_g": 58.0,
        "fat_g": 7.0,
        "cook_minutes": 30,
        "steps": "大米煮至开花, 关火前倒入牛奶搅匀。",
    },
    {
        "name": "醋溜土豆丝",
        "ingredients": [("土豆", "2个"), ("醋", "20ml")],
        "calories": 250,
        "protein_g": 5.0,
        "carb_g": 48.0,
        "fat_g": 4.0,
        "cook_minutes": 12,
        "steps": "土豆丝泡水沥干, 大火快炒, 沿锅边烹醋。",
    },
    {
        "name": "虾仁炒蛋",
        "ingredients": [("虾仁", "150g"), ("鸡蛋", "3个")],
        "calories": 330,
        "protein_g": 32.0,
        "carb_g": 5.0,
        "fat_g": 20.0,
        "cook_minutes": 12,
        "steps": "虾仁焯水, 与蛋液同炒至刚凝固。",
    },
]

MEAL_ORDER = ("lunch", "dinner")
DAYS = 7

# 与 services/replacement_service.py 的 DISH_PROMPT_MARKER 一致:
# 提示词里出现这个说法就说明这是在「换一道」, 只该返回单道菜。
DISH_PROMPT_MARKER = "只生成一道菜"

# 「换一道」演示用菜: 刻意不在 DEMO_WEEK 里, 否则会被"不要与已有菜重名"挡掉。
# 注意: 演示客户端必须能提供「多道互不相同」的替换菜, 只用一道的话,
# 第一次换进菜单后, 之后每次都会因"与已有菜重名"被挡 -> 重试后仍失败 -> 502
# (见 logs/backend.log 里连续的 `AI 换一道结果不合格(与已有菜重名): 番茄牛腩`)。
DEMO_DISH: Dict[str, Any] = {
    "name": "番茄牛腩",
    "ingredients": [("牛腩", "300g"), ("番茄", "2个"), ("洋葱", "1个")],
    "calories": 430,
    "protein_g": 35.0,
    "carb_g": 20.0,
    "fat_g": 24.0,
    "cook_minutes": 28,
    "steps": "牛腩焯水后与番茄同炖 20 分钟, 收汁前加洋葱。",
}

# 「换一道」轮换菜池: 名字均不同于 DEMO_WEEK, 且不含花生等常见过敏源。
DEMO_REPLACEMENT_DISHES: List[Dict[str, Any]] = [
    DEMO_DISH,
    {
        "name": "麻婆豆腐",
        "ingredients": [("豆腐", "1块"), ("牛肉末", "100g"), ("豆瓣酱", "15g")],
        "calories": 340,
        "protein_g": 22.0,
        "carb_g": 18.0,
        "fat_g": 19.0,
        "cook_minutes": 20,
        "steps": "豆腐切块焯水, 牛肉末炒散后下豆瓣酱, 加豆腐小火烧 5 分钟勾芡。",
    },
    {
        "name": "宫保鸡丁",
        "ingredients": [("鸡胸肉", "250g"), ("干辣椒", "10g"), ("黄瓜", "1根")],
        "calories": 400,
        "protein_g": 38.0,
        "carb_g": 16.0,
        "fat_g": 20.0,
        "cook_minutes": 18,
        "steps": "鸡胸肉切丁上浆, 干辣椒爆香后下鸡丁与黄瓜丁, 调糖醋汁翻匀。",
    },
    {
        "name": "清蒸鲈鱼",
        "ingredients": [("鲈鱼", "1条"), ("姜", "1块"), ("葱", "2根")],
        "calories": 280,
        "protein_g": 34.0,
        "carb_g": 3.0,
        "fat_g": 13.0,
        "cook_minutes": 22,
        "steps": "鲈鱼改刀铺姜丝, 大火蒸 8 分钟, 淋蒸鱼豉油撒葱丝泼热油。",
    },
    {
        "name": "咖喱鸡肉饭",
        "ingredients": [("鸡腿肉", "250g"), ("咖喱块", "50g"), ("米饭", "1碗")],
        "calories": 560,
        "protein_g": 30.0,
        "carb_g": 64.0,
        "fat_g": 20.0,
        "cook_minutes": 25,
        "steps": "鸡腿肉煎香, 加水与咖喱块煮 10 分钟至浓稠, 浇在米饭上。",
    },
    {
        "name": "冬瓜排骨汤",
        "ingredients": [("排骨", "300g"), ("冬瓜", "200g"), ("姜", "1块")],
        "calories": 360,
        "protein_g": 26.0,
        "carb_g": 10.0,
        "fat_g": 22.0,
        "cook_minutes": 40,
        "steps": "排骨焯水后与姜片炖 25 分钟, 下冬瓜再煮 10 分钟加盐。",
    },
    {
        "name": "蚝油生菜",
        "ingredients": [("生菜", "1颗"), ("蚝油", "15ml")],
        "calories": 130,
        "protein_g": 5.0,
        "carb_g": 10.0,
        "fat_g": 7.0,
        "cook_minutes": 8,
        "steps": "生菜焯水摆盘, 蚝油加水烧开后淋上。",
    },
    {
        "name": "番茄龙利鱼",
        "ingredients": [("龙利鱼", "300g"), ("番茄", "2个")],
        "calories": 300,
        "protein_g": 32.0,
        "carb_g": 12.0,
        "fat_g": 13.0,
        "cook_minutes": 20,
        "steps": "番茄炒出汁加水煮开, 下龙利鱼块煮 5 分钟调味。",
    },
    {
        "name": "芦笋炒虾仁",
        "ingredients": [("芦笋", "200g"), ("虾仁", "150g")],
        "calories": 240,
        "protein_g": 30.0,
        "carb_g": 10.0,
        "fat_g": 8.0,
        "cook_minutes": 15,
        "steps": "芦笋切段焯水, 虾仁滑炒变色后下芦笋快炒调味。",
    },
    {
        "name": "香菇青菜",
        "ingredients": [("香菇", "4个"), ("青菜", "1把")],
        "calories": 150,
        "protein_g": 7.0,
        "carb_g": 14.0,
        "fat_g": 7.0,
        "cook_minutes": 12,
        "steps": "香菇切片爆香, 下青菜大火快炒至断生。",
    },
    {
        "name": "辣子鸡丁",
        "ingredients": [("鸡腿肉", "250g"), ("干辣椒", "15g"), ("花椒", "5g")],
        "calories": 450,
        "protein_g": 34.0,
        "carb_g": 12.0,
        "fat_g": 28.0,
        "cook_minutes": 20,
        "steps": "鸡腿肉切丁炸至金黄, 与干辣椒花椒同炒出香。",
    },
    {
        "name": "罗宋汤",
        "ingredients": [("牛腩", "200g"), ("番茄", "2个"), ("土豆", "1个"), ("胡萝卜", "1根")],
        "calories": 380,
        "protein_g": 24.0,
        "carb_g": 28.0,
        "fat_g": 18.0,
        "cook_minutes": 45,
        "steps": "牛腩焯水炖软, 下番茄土豆胡萝卜煮 20 分钟至汤浓。",
    },
]


def build_demo_week_menu() -> Dict[str, Any]:
    """把 DEMO_WEEK 铺成 7 天 x (午餐, 晚餐); 日期留空由后端按周一对齐"""
    days: List[Dict[str, Any]] = []
    for day_index in range(DAYS):
        meals: Dict[str, Any] = {}
        for meal_index, meal_type in enumerate(MEAL_ORDER):
            recipe = DEMO_WEEK[(day_index * len(MEAL_ORDER) + meal_index) % len(DEMO_WEEK)]
            meals[meal_type] = {
                "recipes": [
                    {
                        "name": recipe["name"],
                        "ingredients": [
                            {"name": name, "quantity": amount, "unit": ""}
                            for name, amount in recipe["ingredients"]
                        ],
                        "calories": recipe["calories"],
                        "protein_g": recipe["protein_g"],
                        "carb_g": recipe["carb_g"],
                        "fat_g": recipe["fat_g"],
                        "cook_minutes": recipe["cook_minutes"],
                        "steps": recipe["steps"],
                    }
                ]
            }
        days.append({"date": "", "day_type": "weekend" if day_index >= 5 else "weekday", "meals": meals})
    return {"week_menu": days}


def _dish_to_payload(dish: Dict[str, Any]) -> Dict[str, Any]:
    """把菜池里的 raw dish 转成 DishGenerate 兼容的 JSON 结构"""
    return {
        "name": dish["name"],
        "ingredients": [
            {"name": name, "quantity": amount, "unit": ""}
            for name, amount in dish["ingredients"]
        ],
        "calories": dish["calories"],
        "protein_g": dish["protein_g"],
        "carb_g": dish["carb_g"],
        "fat_g": dish["fat_g"],
        "cook_minutes": dish["cook_minutes"],
        "steps": dish["steps"],
    }


def build_demo_dish() -> Dict[str, Any]:
    """单菜 JSON, 结构对齐 schemas.recipe.DishGenerate (默认返回第一道演示菜)"""
    return _dish_to_payload(DEMO_DISH)


# 「不要与这些菜重名」/「避开」后面的名单 -> 演示客户端据此避开重复
_EXCLUDE_MARKERS = ("不要与这些菜重名", "不要与已有菜重名", "避开")
# 「过敏源 / 忌口」后面的名单 -> 演示客户端据此避开忌口食材
_RESTRICTED_MARKERS = ("过敏源", "忌口")


def _split_names(raw: str) -> List[str]:
    return [part.strip() for part in re.split(r"[,，、;；]", raw) if part.strip()]


def _names_after_markers(text: str, markers: Sequence[str]) -> List[str]:
    """从提示词文本里抽出 marker 那一行紧跟的逗号名单"""
    names: List[str] = []
    for line in text.splitlines():
        for marker in markers:
            if marker not in line:
                continue
            sep = ":" if ":" in line else ("：" if "：" in line else "")
            if not sep:
                continue
            names.extend(_split_names(line.split(sep, 1)[1]))
    return names


def _dish_haystack(dish: Dict[str, Any]) -> List[str]:
    return [dish["name"]] + [name for name, _amount in dish["ingredients"]]


def pick_replacement_dish(
    messages: List[Dict[str, str]], cursor: int = 0
) -> tuple[Dict[str, Any], int]:
    """按提示词里的「不要与已有菜重名 / 避开过敏源」约束, 从菜池轮换挑一道。

    返回 ``(dish, next_cursor)``。整池都被排除时, 退回轮换并加后缀保证名字唯一,
    免得演示环境里反复「换一道」必然撞重名 -> 502。
    """
    text = "\n".join((message.get("content") or "") for message in messages)
    excluded = set(_names_after_markers(text, _EXCLUDE_MARKERS))
    restricted = _names_after_markers(text, _RESTRICTED_MARKERS)
    pool = DEMO_REPLACEMENT_DISHES
    size = len(pool)

    for offset in range(size):
        dish = pool[(cursor + offset) % size]
        names = _dish_haystack(dish)
        if dish["name"] in excluded:
            continue
        if any(any(word in item for word in restricted) for item in names):
            continue
        return dish, (cursor + offset + 1) % size

    fallback = dict(pool[cursor % size])
    fallback["name"] = f"{fallback['name']}·特调{cursor + 1}"
    return fallback, (cursor + 1) % size


class DemoLLMClient(LLMClient):
    """假客户端, 只在 APP__LLM__DEMO=true 时启用。

    整周请求返回固定的 DEMO_WEEK; 单菜「换一道」请求会读提示词里
    「不要与这些菜重名」的名单, 从 DEMO_REPLACEMENT_DISHES 轮换挑一道,
    保证连续多次「换一道」不会反复返回同一道而被判重名。
    """

    def __init__(self, payload: Optional[Dict[str, Any]] = None):
        super().__init__(name="local-demo")
        self.payload = payload or build_demo_week_menu()
        self._dish_cursor = 0

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        if any(DISH_PROMPT_MARKER in (message.get("content") or "") for message in messages):
            dish, self._dish_cursor = pick_replacement_dish(messages, self._dish_cursor)
            return json.dumps(_dish_to_payload(dish), ensure_ascii=False)
        return json.dumps(self.payload, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True
