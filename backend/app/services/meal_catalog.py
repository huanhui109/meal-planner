"""Grounded candidates and complete-meal composition; no model calls."""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.local_pool import LOCAL_DISHES
from app.models.recipe import Recipe
from app.schemas.meal import MealContext
from app.services.decision_service import Candidate, DecisionService, normalize_dish_name
from app.services.dish_rules import dish_only
from app.services.intent_service import _looks_like_meat
from app.services.pricing_service import PricedRow, PricingService

STAPLES = {"盐", "食盐", "水", "食用油", "油", "生抽", "老抽", "白糖", "糖", "料酒", "酱油"}
INVALID_INGREDIENTS = {
    "主料", "辅料", "调料", "配料", "材料", "调味料", "香料包",
    "蒸架", "炒锅", "平底锅", "电饭煲", "烤箱", "锅", "碗",
}
ALLERGEN_GROUPS = {
    "海鲜": ("鱼", "虾", "蟹", "贝", "蚝", "蛤", "鱿鱼", "海鲜", "虾酱"),
    "坚果": ("花生", "核桃", "腰果", "杏仁", "松子", "坚果"),
    "乳": ("奶", "黄油", "乳", "芝士", "奶酪"),
    "蛋": ("蛋", "沙拉酱", "蛋黄酱"),
    "大豆": ("豆腐", "豆浆", "豆干", "大豆", "酱油", "生抽", "老抽", "豆瓣"),
    "小麦": (
        "面粉", "面条", "面包", "饺", "馄饨", "小麦", "酱油", "生抽", "老抽",
        "意大利面", "意面", "挂面", "吐司", "馒头", "花卷", "饼",
    ),
}
FOOD_ALIASES = {
    "米": ("米", "饭", "粥"),
    "大米": ("大米", "米饭", "丼饭", "粥", "米线", "米粉"),
    "牛肉": ("牛肉", "肥牛", "牛腩", "牛排", "牛腱", "牛柳"),
    "猪肉": ("猪", "五花", "里脊", "排骨", "肉末", "肉丝", "肉片", "培根", "火腿", "香肠"),
    "鸡肉": ("鸡肉", "鸡腿", "鸡翅", "鸡胸", "鸡丁", "鸡块", "鸡柳"),
}
FOOD_ALIASES["肉"] = tuple({
    "肉", "鸭", "鹅", "羊", *FOOD_ALIASES["牛肉"], *FOOD_ALIASES["猪肉"], *FOOD_ALIASES["鸡肉"],
})


def ingredient_matches(left: str, right: str) -> bool:
    a, b = normalize_dish_name(left), normalize_dish_name(right)
    return bool(a and b and (a in b or b in a))


def forbidden_words(words: list[str]) -> list[str]:
    synonyms = {"牛奶": "乳", "乳制品": "乳", "鸡蛋": "蛋", "豆类": "大豆", "麸质": "小麦", "鱼虾": "海鲜"}
    words = [synonyms.get(word, word) for word in words]
    expanded = set(words)
    for word in words:
        expanded.update(FOOD_ALIASES.get(word, ()))
        for group, aliases in ALLERGEN_GROUPS.items():
            if word == group or word in (f"{group}过敏", f"{group}类") or word in aliases:
                expanded.update(aliases)
    return sorted(expanded)


@dataclass
class MealCandidate:
    key: str
    dish: Candidate
    role: str
    base_servings: Optional[int] = None
    requirements: list[dict] = field(default_factory=list)

    def view(self, servings: int = 1) -> dict:
        scale = servings / self.base_servings if self.base_servings else None
        return {
            "key": self.key,
            "recipe_id": self.dish.id,
            "name": self.dish.name,
            "role": self.role,
            "ingredients": self.dish.ingredients,
            "steps": self.dish.steps,
            "estimated_minutes": self.dish.minutes,
            "estimated_cost": round(self.dish.cost * scale, 2)
            if self.dish.cost is not None and scale is not None else None,
            "spice": self.dish.spice,
            "base_servings": self.base_servings,
            "requirements": [
                {**line, "quantity": round(line["quantity"] * scale, 3)
                 if line["quantity"] is not None and scale is not None else None}
                for line in self.requirements
            ],
        }


def meal_role(dish: Candidate) -> Optional[str]:
    if dish.name in ("米饭", "白米饭", "杂粮饭", "糙米饭", "馒头", "花卷", "白粥", "小米粥", "玉米粥", "吐司"):
        return "staple"
    has_protein = _looks_like_meat(dish.haystack) or any(
        x in dish.haystack for x in ("蛋", "豆腐", "豆干")
    )
    if not has_protein and (
        dish.name.endswith("粥") or any(x in dish.name for x in ("吐司", "面包", "馒头", "花卷"))
    ):
        return "staple"
    if dish.category in ("主食", "面食") or "一锅出" in dish.tags:
        return "complete"
    if dish.category in ("汤", "汤羹"):
        return "soup"
    if has_protein:
        return "main"
    vegetables = (
        "白菜", "青菜", "油麦菜", "生菜", "包菜", "娃娃菜", "芥菜", "空心菜",
        "菠菜", "芹菜", "韭菜", "西兰花", "菜花", "花椰菜", "黄瓜", "冬瓜",
        "苦瓜", "南瓜", "丝瓜", "西葫芦", "茄子", "番茄", "西红柿", "土豆",
        "萝卜", "山药", "莲藕", "笋", "菇", "木耳", "海带", "秋葵", "豆角",
        "豇豆", "荷兰豆", "豌豆", "毛豆", "豆芽", "莴笋", "洋葱", "青椒",
    )
    if any(word in " ".join([dish.name, *dish.ingredients]) for word in vegetables):
        return "side"
    return None


async def load_meal_catalog(db: AsyncSession) -> list[MealCandidate]:
    rows = list((await db.execute(
        select(Recipe).where(dish_only()).order_by(Recipe.id).limit(600)
    )).scalars().all())
    result = []
    known = set()
    for recipe in rows:
        dish = DecisionService._from_recipe(recipe)
        if not dish.steps or not dish.ingredients or any(
            name in INVALID_INGREDIENTS
            or re.fullmatch(r"(?:单人|双人|\d+人)(?:份)?|人数|份数", name)
            for name in dish.ingredients
        ):
            continue
        role = meal_role(dish)
        if role is None:
            continue
        known.add(normalize_dish_name(dish.name))
        priced = PricingService().estimate([
            PricedRow(
                ingredient_name=ri.ingredient.name, quantity=ri.quantity, unit=ri.unit,
                reference_price=ri.ingredient.reference_price, standard_unit=ri.ingredient.standard_unit or "",
            ) for ri in recipe.recipe_ingredients if ri.ingredient
        ])
        dish.cost = priced.total if priced.priced_items == len(recipe.recipe_ingredients) and priced.priced_items else None
        result.append(MealCandidate(
            key=f"recipe:{recipe.id}", dish=dish, role=role,
            base_servings=recipe.base_servings,
            requirements=[
                {"ingredient_id": ri.ingredient_id, "name": ri.ingredient.name,
                 "quantity": ri.quantity, "unit": ri.unit}
                for ri in recipe.recipe_ingredients if ri.ingredient
            ],
        ))
    for item in LOCAL_DISHES:
        if normalize_dish_name(item["name"]) in known:
            continue
        dish = DecisionService._from_pool(item)
        role = meal_role(dish)
        if role is None:
            continue
        key = hashlib.sha256(dish.name.encode()).hexdigest()[:16]
        result.append(MealCandidate(key=f"local:{key}", dish=dish, role=role))
    rice = Candidate(
        id=None, name="米饭", cuisine="家常", category="主食", main="大米",
        minutes=25, calories=0, difficulty=1, spice=0, light=True, cover="",
        tags=[], flavors=[], ingredients=["大米", "水"],
        steps=["每人约 75 克生米，淘洗后放入电饭煲", "按电饭煲刻度加水，启动煮饭程序"],
    )
    result.append(MealCandidate(
        key="staple:rice", dish=rice, role="staple", base_servings=1,
        requirements=[{"ingredient_id": None, "name": "大米", "quantity": 75, "unit": "g"}],
    ))
    return result


def filter_catalog(
    catalog: list[MealCandidate], context: MealContext, restrictions: list[str],
    eaten_names: set[str], tools: Optional[set[str]] = None,
) -> list[MealCandidate]:
    avoids = forbidden_words(list(set(restrictions + context.avoid)))
    result = []
    for candidate in catalog:
        dish = candidate.dish
        if dish.meal_slots and context.meal_slot not in dish.meal_slots:
            continue
        if any(word in dish.haystack for word in avoids):
            continue
        if context.vegetarian and _looks_like_meat(dish.haystack):
            continue
        if dish.spice > context.max_spice:
            continue
        if context.max_spice == 0 and any(
            word in dish.haystack for word in ("辣", "老干妈", "豆瓣酱", "剁椒", "红油", "小米椒")
        ):
            continue
        if context.light and not dish.light and candidate.role != "staple":
            continue
        if context.avoid_recent and normalize_dish_name(dish.name) in eaten_names:
            continue
        if context.mode != "takeout":
            if dish.minutes > context.max_minutes:
                continue
            if tools is not None and any(tool not in tools for tool in dish.tools if tool != "none"):
                continue
        result.append(candidate)
    return result


def meal_minutes(candidates: list[MealCandidate]) -> int:
    # Rice can cook unattended while the other dishes are prepared.
    return max(
        sum(c.dish.minutes for c in candidates if c.role != "staple"),
        max((c.dish.minutes for c in candidates if c.role == "staple"), default=0),
    )


def composition_error(candidates: list[MealCandidate], context: MealContext) -> Optional[str]:
    if len({normalize_dish_name(c.dish.name) for c in candidates}) != len(candidates):
        return "同一餐不能重复选择同一道菜"
    if any(c.role == "complete" for c in candidates):
        if context.servings <= 1 or any(c.role == "side" for c in candidates):
            return None
        return "家庭餐还需要一道蔬菜搭配"
    roles = {c.role for c in candidates}
    if not {"main", "side", "staple"}.issubset(roles):
        return "请组成完整一餐：一道主菜、一道蔬菜和主食，或一份完整主食餐"
    return None


def validate_composition(candidates: list[MealCandidate], context: MealContext) -> Optional[str]:
    error = composition_error(candidates, context)
    if error:
        return error
    if context.mode != "takeout" and meal_minutes(candidates) > context.max_minutes:
        return "这组菜的参考总用时超过了时间上限，请换更快的组合或调整时间"
    costs = [c.view(context.servings)["estimated_cost"] for c in candidates]
    if context.mode != "takeout" and context.budget and all(x is not None for x in costs):
        if sum(costs) > context.budget:
            return "这组菜的估算成本超过了本餐预算"
    return None


def compose_meal(
    catalog: list[MealCandidate], context: MealContext, owned: list[str], rejected: set[str],
    seed: str,
) -> Optional[list[MealCandidate]]:
    def score(candidate: MealCandidate) -> float:
        stock = sum(
            any(ingredient_matches(ing, name) for name in owned)
            for ing in candidate.dish.ingredients if ing not in STAPLES
        ) if context.use_fridge else 0
        variety = int(hashlib.sha256(f"{seed}:{candidate.key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return stock * 2 + variety - candidate.dish.minutes / 180

    ranked = sorted(catalog, key=score, reverse=True)
    groups = {role: [c for c in ranked if c.role == role][:16]
              for role in ("complete", "main", "side", "staple")}
    choices: list[list[MealCandidate]] = []
    for complete in groups["complete"]:
        if context.servings == 1:
            choices.append([complete])
        else:
            choices.extend([[complete, side] for side in groups["side"]])
    choices.extend(
        [list(parts) for parts in itertools.product(groups["main"], groups["side"], groups["staple"])]
    )
    valid = [parts for parts in choices if validate_composition(parts, context) is None]
    if not valid:
        return None
    fresh = [
        parts for parts in valid
        if "|".join(sorted(c.key for c in parts)) not in rejected
    ]
    if not fresh:
        return None
    return max(fresh, key=lambda parts: sum(score(c) for c in parts) / len(parts))
