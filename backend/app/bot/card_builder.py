"""飞书消息卡片构建器"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class CardBuilder:
    """构建飞书交互式卡片"""

    @staticmethod
    def build_daily_menu_card(
        date: str,
        meals: Dict[str, List[Dict[str, Any]]],
        total_calories: Optional[int] = None,
    ) -> Dict[str, Any]:
        """构建每日菜单卡片"""
        elements: List[Dict[str, Any]] = []

        for meal_type, recipes in meals.items():
            meal_label = {"lunch": "午餐", "dinner": "晚餐", "breakfast": "早餐"}.get(meal_type, meal_type)
            lines = [f"**{meal_label}**"]
            for r in recipes:
                line = f"- {r.get('name', '')}"
                if r.get("calories"):
                    line += f" ({r['calories']}kcal)"
                lines.append(line)
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "\n".join(lines)},
                }
            )

        if total_calories:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**总计: {total_calories} kcal**"},
                }
            )

        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看完整菜单"},
                        "type": "default",
                    },
                    {"tag": "button", "text": {"tag": "plain_text", "content": "重新生成"}, "type": "danger"},
                ],
            }
        )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"今日菜单 - {date}"},
                "template": "blue",
            },
            "elements": elements,
        }

    @staticmethod
    def build_order_reminder_card(
        missing_ingredients: List[str],
        estimated_cost: Optional[float] = None,
    ) -> Dict[str, Any]:
        """构建补单提醒卡片"""
        ingredients_text = "\n".join([f"- {name}" for name in missing_ingredients[:10]])
        if len(missing_ingredients) > 10:
            ingredients_text += f"\n... 等 {len(missing_ingredients)} 项"

        cost_text = f"\n预估花费: ¥{estimated_cost:.0f}" if estimated_cost else ""

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "补单提醒"},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**以下食材库存不足:**\n{ingredients_text}{cost_text}",
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "一键下单"},
                            "type": "primary",
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "调整菜单"},
                            "type": "default",
                        },
                    ],
                },
            ],
        }

    @staticmethod
    def build_expiry_alert_card(
        expiring_items: List[Dict[str, str]],
        urgency: str = "warning",
    ) -> Dict[str, Any]:
        """构建保质期提醒卡片"""
        template = "red" if urgency == "critical" else "orange"
        items_text = "\n".join([f"- {item['name']}: {item['expiry_date']} 到期" for item in expiring_items])

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "临期食材提醒" if urgency == "warning" else "紧急: 即将过期",
                },
                "template": template,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": items_text}},
            ],
        }

    @staticmethod
    def build_text_card(title: str, content: str, template: str = "blue") -> Dict[str, Any]:
        """构建通用文本卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
        }
