"""本地演示 LLM - 不联网, 返回固定的一周菜单

用途: 本地部署 / 演示 / 前端联调。开启后整条生成链路 (落库、计价、营养、预算、
多样性、采购清单、库存扣减) 全部真实执行, 只有「模型输出」这一步是假的。
生产环境必须保持 APP__LLM__DEMO=false。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.llm.base import LLMClient

DEMO_WEEK: List[Dict[str, Any]] = [
    {
        "name": "西红柿炒鸡蛋",
        "ingredients": [("西红柿", "2个"), ("鸡蛋", "3个")],
        "calories": 320, "protein_g": 22.0, "carb_g": 18.0, "fat_g": 17.0,
        "cook_minutes": 15, "steps": "鸡蛋打散炒至凝固盛出, 西红柿炒出汁后混合, 加盐调味。",
    },
    {
        "name": "青椒土豆丝",
        "ingredients": [("土豆", "2个"), ("青椒", "2个"), ("醋", "10ml")],
        "calories": 260, "protein_g": 6.0, "carb_g": 48.0, "fat_g": 5.0,
        "cook_minutes": 15, "steps": "土豆切丝泡水去淀粉, 热油下锅大火快炒, 出锅前烹醋。",
    },
    {
        "name": "香菇滑鸡",
        "ingredients": [("鸡胸肉", "200g"), ("香菇", "4个"), ("姜", "1块")],
        "calories": 420, "protein_g": 44.0, "carb_g": 12.0, "fat_g": 20.0,
        "cook_minutes": 25, "steps": "鸡胸肉切片用淀粉抓匀, 与香菇同炒, 加姜丝去腥。",
    },
    {
        "name": "蒜蓉西蓝花",
        "ingredients": [("西蓝花", "1颗"), ("蒜", "1头")],
        "calories": 180, "protein_g": 10.0, "carb_g": 16.0, "fat_g": 8.0,
        "cook_minutes": 12, "steps": "西蓝花掰小朵焯水, 蒜末爆香后翻炒 1 分钟。",
    },
    {
        "name": "家常豆腐",
        "ingredients": [("豆腐", "1块"), ("胡萝卜", "1根"), ("酱油", "15ml")],
        "calories": 300, "protein_g": 20.0, "carb_g": 16.0, "fat_g": 17.0,
        "cook_minutes": 20, "steps": "豆腐切块两面煎黄, 加胡萝卜片与酱油小火烧 5 分钟。",
    },
    {
        "name": "洋葱炒鸡蛋",
        "ingredients": [("洋葱", "1个"), ("鸡蛋", "3个")],
        "calories": 290, "protein_g": 20.0, "carb_g": 14.0, "fat_g": 17.0,
        "cook_minutes": 12, "steps": "洋葱切丝炒软, 倒入蛋液翻炒至凝固。",
    },
    {
        "name": "清炒菠菜",
        "ingredients": [("菠菜", "1把"), ("蒜", "1头")],
        "calories": 140, "protein_g": 8.0, "carb_g": 10.0, "fat_g": 7.0,
        "cook_minutes": 10, "steps": "菠菜焯水 10 秒去草酸, 蒜末爆香后快炒。",
    },
    {
        "name": "红烧排骨",
        "ingredients": [("排骨", "500g"), ("姜", "1块"), ("白糖", "15g")],
        "calories": 640, "protein_g": 38.0, "carb_g": 18.0, "fat_g": 45.0,
        "cook_minutes": 45, "steps": "排骨焯水, 炒糖色后加姜片与热水, 小火炖 30 分钟收汁。",
    },
    {
        "name": "番茄鸡蛋面",
        "ingredients": [("面条", "150g"), ("西红柿", "2个"), ("鸡蛋", "2个")],
        "calories": 520, "protein_g": 24.0, "carb_g": 74.0, "fat_g": 14.0,
        "cook_minutes": 20, "steps": "西红柿炒出汁加水煮开, 下番茄汤底与面条, 最后淋蛋花。",
    },
    {
        "name": "木耳炒白菜",
        "ingredients": [("白菜", "1颗"), ("木耳", "30g")],
        "calories": 160, "protein_g": 6.0, "carb_g": 20.0, "fat_g": 6.0,
        "cook_minutes": 15, "steps": "木耳提前泡发, 与白菜帮先炒后下叶。",
    },
    {
        "name": "香煎鸡胸肉",
        "ingredients": [("鸡胸肉", "250g"), ("黑胡椒", "5g")],
        "calories": 380, "protein_g": 52.0, "carb_g": 3.0, "fat_g": 18.0,
        "cook_minutes": 18, "steps": "鸡胸肉拍松, 撒黑胡椒与盐腌制 10 分钟后两面煎熟。",
    },
    {
        "name": "牛奶粥",
        "ingredients": [("牛奶", "300ml"), ("大米", "80g")],
        "calories": 340, "protein_g": 12.0, "carb_g": 58.0, "fat_g": 7.0,
        "cook_minutes": 30, "steps": "大米煮至开花, 关火前倒入牛奶搅匀。",
    },
    {
        "name": "醋溜土豆丝",
        "ingredients": [("土豆", "2个"), ("醋", "20ml")],
        "calories": 250, "protein_g": 5.0, "carb_g": 48.0, "fat_g": 4.0,
        "cook_minutes": 12, "steps": "土豆丝泡水沥干, 大火快炒, 沿锅边烹醋。",
    },
    {
        "name": "虾仁炒蛋",
        "ingredients": [("虾仁", "150g"), ("鸡蛋", "3个")],
        "calories": 330, "protein_g": 32.0, "carb_g": 5.0, "fat_g": 20.0,
        "cook_minutes": 12, "steps": "虾仁焯水, 与蛋液同炒至刚凝固。",
    },
]

MEAL_ORDER = ("lunch", "dinner")
DAYS = 7


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


class DemoLLMClient(LLMClient):
    """固定输出的假客户端, 只在 APP__LLM__DEMO=true 时启用"""

    def __init__(self, payload: Optional[Dict[str, Any]] = None):
        super().__init__(name="local-demo")
        self.payload = payload or build_demo_week_menu()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        return json.dumps(self.payload, ensure_ascii=False)

    async def is_available(self) -> bool:
        return True
