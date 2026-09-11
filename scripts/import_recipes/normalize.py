"""归一化 - 把两个异构数据源统一成 RecipeRecord

统一字段语义与既有 ``recipe`` / ``recipe_ingredient`` 表对齐:
  * ``cuisine``      <- 分类 (proj.kitchen category / HowToCook 目录名)
  * ``difficulty``   <- 1-5 (星级 或 简单/中等/困难)
  * ``cook_minutes`` <- 预估烹饪时间
  * ``calories``     <- 预估卡路里 (HowToCook 才有, 其余交给 LLM 回填)
  * ``protein_g`` / ``carb_g`` / ``fat_g``  -> 多数缺失, 交给 LLM 回填
  * ``steps``        <- 操作步骤 + 附加内容/小贴士 + 工具
  * ``ingredients``  <- 用量文本经 ``normalize_amount`` 拆成 数量+单位
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ingredient_amount import normalize_amount  # noqa: E402

STAR = "★"
NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
MAX_INGREDIENTS_PER_RECIPE = 25

# HowToCook 目录名 -> 中文分类
HOWTOCOOK_CATEGORIES = {
    "aquatic": "水产",
    "breakfast": "早餐",
    "condiment": "调料",
    "dessert": "甜品",
    "drink": "饮品",
    "meat_dish": "荤菜",
    "semi-finished": "半成品",
    "soup": "汤羹",
    "staple": "主食",
    "vegetable_dish": "素菜",
}

DIFFICULTY_TEXT = {
    "简单": 1,
    "容易": 1,
    "入门": 1,
    "中等": 3,
    "普通": 3,
    "困难": 5,
    "复杂": 5,
    "大师": 5,
}

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class IngredientRecord:
    name: str
    quantity: Optional[float]
    unit: str
    amount_text: str


@dataclass
class RecipeRecord:
    name: str
    cuisine: Optional[str] = None
    difficulty: Optional[int] = None
    cook_minutes: Optional[int] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carb_g: Optional[float] = None
    fat_g: Optional[float] = None
    steps: str = ""
    source: str = "howtocook"
    ingredients: List[IngredientRecord] = field(default_factory=list)
    sources: set = field(default_factory=set)


def clean_dish_name(raw: str) -> str:
    name = (raw or "").strip()
    name = re.sub(r"\s+", "", name)
    name = re.sub(r"的做法$", "", name)
    return name


def map_difficulty(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(1, min(5, int(value)))
    text = str(value).strip()
    if not text:
        return None
    if STAR in text:
        return max(1, min(5, text.count(STAR)))
    if text in DIFFICULTY_TEXT:
        return DIFFICULTY_TEXT[text]
    match = NUMBER.search(text)
    if match:
        return max(1, min(5, int(float(match.group(1)))))
    return None


def _extract_number(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = NUMBER.search(str(text))
    return float(match.group(1)) if match else None


# 食材名: 中文为主, 去掉括号备注, 拒绝数字/换算说明/过长句子
ING_NAME_MAX = 15
_BAD_NAME_CHARS = set("=：:*×~（）()[]{}＜＞<>\"'，,。、")

# 说明性句子 (不是食材) 的判据: 命中即丢弃
_PROSE_MARKERS = (
    "用量", "容量", "体积", "质量", "时间", "大小", "差不多", "足够", "忽略",
    "可以", "即可", "如果", "根据", "按照", "其中", "每份", "制作", "准备",
    "决策", "最晚", "放入", "一顿", "一个人", "大约", "因人", "以上",
    "以下", "左右", "口味", "的", "是", "建议", "需要", "注意", "混合后", "总共", "部分",
)
# 厨具/容器 (不是食材) 的判据
_TOOL_MARKERS = (
    "锅", "煲", "炉", "烤箱", "微波", "搅拌", "料理机", "打蛋器", "擀面杖",
    "菜刀", "砧板", "菜板", "容器", "密封", "保鲜", "厨具", "灶具", "碟",
)
# 数量词: 前置/后置都可能是 `一个鸡蛋` / `八角 两个` / `10g 吉利丁` 这种写法
_COUNT_UNIT_CHARS = "个只根颗枚片块杯勺汤匙茶匙瓣把条斤两袋包碗盘份张头棵朵盒瓶罐"
_COUNT_UNIT_WORDS = [
    "个", "只", "根", "颗", "枚", "片", "块", "杯", "勺", "汤匙", "茶匙", "瓣",
    "把", "条", "斤", "两", "袋", "包", "碗", "盘", "份", "张", "头", "棵", "朵",
    "盒", "瓶", "罐",
]
_UNITS_RE = "|".join(
    ["千克", "毫升", "kg", "KG", "mL", "ML", "ml", "克", "g", "G", "L", "l", "升", *_COUNT_UNIT_WORDS]
)
_NUM = r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百半几两]+)"
_LEADING_COUNT = re.compile(rf"^\s*{_NUM}\s*[小大]?\s*(?:{_UNITS_RE})\s*")
_TRAILING_COUNT = re.compile(rf"\s*{_NUM}\s*[小大]?\s*(?:{_UNITS_RE})\s*$")
# 句中夹着数量词 (如 `调一个灵魂料汁儿`) 基本是说明性句子
_INLINE_COUNT = re.compile(rf"[一二三四五六七八九十半两][{_COUNT_UNIT_CHARS}]")
_OPTION_SPLIT = re.compile(r"\s*(?:或|or|Or|OR)\s*")

# `西红柿 1 个` / `豆腐 100 g` / `食用油 10-20ml`
_AMOUNT_TAIL = re.compile(r"^(?P<name>.+?)\s+(?P<amount>\d+(?:[.\-~]\d+)*\s*[^\d\s]*)$")
# `100 ml 水` (数量在前, 单位与名称间有空格)
_AMOUNT_HEAD = re.compile(r"^(?P<amount>\d+(?:[.\-~]\d+)*\s*[^\d\s]*)\s+(?P<name>.+)$")
# `1 枚咸鸭蛋` / `2 个鸡蛋` (数量 + 中文量词 + 名称, 量词与名称间无空格)
_AMOUNT_HEAD_CN = re.compile(
    rf"^(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[{_COUNT_UNIT_CHARS}])\s*(?P<name>\S.*)$"
)


def _clean_name(raw: str) -> str:
    name = re.sub(r"[（(].*?[)）]", " ", raw or "")
    return name.strip(" -—·:：,，。、\t")


def _finalize_name(raw: str) -> str:
    """把食材名收敛成名词短语: 去 markdown、去选项、去数量词"""
    text = re.sub(r"[`*_~½¼¾]", "", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = _OPTION_SPLIT.split(text)[0]
    if "/" in text:
        text = text.split("/")[0]
    text = _LEADING_COUNT.sub("", text)
    text = _TRAILING_COUNT.sub("", text)
    text = re.sub(r"^\s*\d+(?:\.\d+)?\s*", "", text)
    text = re.sub(r"\s*[约~≈]\s*$", "", text)
    text = re.sub(r"\s*各\s*$", "", text)
    text = re.sub(r"\s+[大小]\s*$", "", text)
    return text.strip(" -—·:：,，。、\t")


def _plausible_ingredient(name: str) -> bool:
    if not name or len(name) > ING_NAME_MAX:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    if any(ch in _BAD_NAME_CHARS for ch in name):
        return False
    if any(marker in name for marker in _PROSE_MARKERS):
        return False
    if any(marker in name for marker in _TOOL_MARKERS):
        return False
    if len(name) > 6 and _INLINE_COUNT.search(name):
        return False
    if name in _COUNT_UNIT_WORDS:
        return False
    return "份数" not in name and "数量" not in name and "计划" not in name


# ---------- proj.kitchen name 字段清洗 ----------
# 该源的 ingredients[].name 常混入用量与说明, 例如:
#   '肋排 =' / '里脊肉 200g' / '叶菜类蔬菜：300g' / '干辣椒（依照个人口味）2-3 个，切碎'
_TEMP_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)?\s*[°℃]\s*[CF]?\s*")
_EMBEDDED_AMOUNT = re.compile(
    r"\d+(?:\.\d+)?\s*"
    r"(?:kg|KG|mL|ML|ml|g|G|L|l|克|千克|毫升|升|斤|两|个|只|根|颗|枚|片|块|杯|勺|瓣|把|条)"
)
_PLACEHOLDER_AMOUNTS = {"", "适量", "少许", "少量", "各适量", "适量即可"}


def _is_placeholder_amount(text: str) -> bool:
    return (text or "").strip() in _PLACEHOLDER_AMOUNTS


def _core_ingredient_name(raw: str) -> str:
    """从脏 name 里挤出真正的食材名 (不含用量/单位/备注)"""
    text = (raw or "").strip()
    text = text.split("=")[0]
    text = re.split(r"[：:]", text)[0]
    text = _TEMP_PREFIX.sub("", text)
    text = re.split(r"[（(]", text)[0]
    text = re.split(r"[，,。；;]", text)[0]
    text = _LEADING_COUNT.sub("", text)
    text = re.split(r"\d", text)[0]
    return _finalize_name(text)


def clean_proj_ingredient(raw_name: str, raw_amount: str) -> Optional[IngredientRecord]:
    """清洗 proj.kitchen 的 (name, amount) -> IngredientRecord, 脏数据返回 None"""
    name = (raw_name or "").strip()
    if not name:
        return None
    amount_text = (raw_amount or "").strip()

    if "=" in name:
        head, _, tail = name.partition("=")
        if tail.strip() and _is_placeholder_amount(amount_text):
            amount_text = tail.strip()
        name = head
    match = re.match(r"^([^：:]+)[：:]\s*(\d[^：:]*)", name)
    if match:
        if _is_placeholder_amount(amount_text):
            amount_text = match.group(2).strip()
        name = match.group(1)
    if _is_placeholder_amount(amount_text):
        found = _EMBEDDED_AMOUNT.search(name)
        if found:
            amount_text = found.group(0).strip()

    cleaned = _core_ingredient_name(name)
    if not _plausible_ingredient(cleaned):
        return None
    amount = normalize_amount(amount_text or "", "")
    return IngredientRecord(
        name=cleaned,
        quantity=amount.quantity,
        unit=amount.unit,
        amount_text=(amount_text or "")[:50],
    )


def parse_ingredient_line(line: str) -> Optional[IngredientRecord]:
    """解析一行用量 -> (name, quantity, unit, amount_text)

    覆盖 HowToCook 的 `名称 数量 单位` 与少量 `数量 单位 名称` 两种写法,
    并过滤掉「数量 = 份数 * 3g」「叶菜类蔬菜：300g ~ 500g」这类说明行。
    """
    raw = line.strip().lstrip("*-+• \t")
    if not raw or "=" in raw or "：" in raw or ":" in raw:
        return None
    raw = re.split(r"\s*[*×]\s*份数", raw)[0]
    raw = re.split(r"\s*[+＋]\s*", raw)[0]
    raw = re.sub(r"[（(].*?[)）]", " ", raw).strip()
    if not raw:
        return None

    amount_text = ""
    cn_head = _AMOUNT_HEAD_CN.match(raw)
    match = _AMOUNT_TAIL.match(raw)
    if cn_head:
        amount_text = f"{cn_head.group('amount')} {cn_head.group('unit')}"
        name = cn_head.group("name")
    elif match:
        name = match.group("name")
        amount_text = match.group("amount")
    else:
        head = _AMOUNT_HEAD.match(raw)
        if head:
            amount_text = head.group("amount")
            name = head.group("name")
        else:
            name = raw

    name = _finalize_name(_clean_name(name))
    if not _plausible_ingredient(name):
        return None
    amount = normalize_amount(amount_text or "", "")
    return IngredientRecord(
        name=name,
        quantity=amount.quantity,
        unit=amount.unit,
        amount_text=(amount_text or "")[:50],
    )


def compose_steps(steps: Iterable[str], tips: Optional[Iterable[str]] = None, tools: Optional[Iterable[str]] = None) -> str:
    lines: List[str] = []
    for index, step in enumerate(steps, start=1):
        text = re.sub(r"\s+", " ", str(step)).strip().lstrip("*-+• ").strip()
        text = re.sub(r"^\d+[.、)]\s*", "", text)
        if text:
            lines.append(f"{index}. {text}")
    tip_lines = [re.sub(r"\s+", " ", str(t)).strip().lstrip("*-+• ").strip() for t in (tips or [])]
    tip_lines = [t for t in tip_lines if t]
    if tools:
        tool_text = "、".join(str(t).strip() for t in tools if str(t).strip())
        if tool_text:
            tip_lines.append(f"工具: {tool_text}")
    body = "\n".join(lines)
    if tip_lines:
        body += "\n\n【小贴士】" + "\n".join(f"- {t}" for t in tip_lines)
    return body.strip()


# ---------- proj.kitchen ----------

def parse_proj_kitchen(payload: dict) -> Optional[RecipeRecord]:
    name = clean_dish_name(str(payload.get("name") or ""))
    if not name:
        return None
    ingredients: List[IngredientRecord] = []
    seen: set[str] = set()
    for item in payload.get("ingredients") or []:
        if not isinstance(item, dict):
            continue
        record = clean_proj_ingredient(str(item.get("name") or ""), str(item.get("amount") or ""))
        if record and record.name not in seen:
            seen.add(record.name)
            ingredients.append(record)
        if len(ingredients) >= MAX_INGREDIENTS_PER_RECIPE:
            break
    steps = payload.get("steps") or []
    if isinstance(steps, str):
        steps = [steps]
    tips = payload.get("tips")
    tip_list = [tips] if isinstance(tips, str) and tips.strip() else []
    tools = payload.get("tools") or []
    return RecipeRecord(
        name=name,
        cuisine=(str(payload.get("category")).strip() or None) if payload.get("category") else None,
        difficulty=map_difficulty(payload.get("difficulty")),
        cook_minutes=_to_int(_extract_number(str(payload.get("cook_minutes") or ""))),
        steps=compose_steps(steps, tip_list, tools),
        source="proj_kitchen",
        ingredients=ingredients,
        sources={"proj_kitchen"},
    )


# ---------- HowToCook markdown ----------

def _split_sections(text: str) -> Dict[str, str]:
    """按 '## 标题' 切段, 返回 {标题: 正文}"""
    sections: Dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def _bullet_lines(block: str) -> List[str]:
    out: List[str] = []
    for line in (block or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "-", "+")) or re.match(r"^\d+[.)]", stripped):
            out.append(stripped)
    return out


def _labeled_value(text: str, label: str) -> Optional[str]:
    match = re.search(rf"{label}\s*[:：]\s*(.+)", text)
    return match.group(1).strip() if match else None


def parse_howtocook(payload: dict) -> Optional[RecipeRecord]:
    text = str(payload.get("text") or "")
    category = str(payload.get("category") or "")
    title_match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    name = clean_dish_name(title_match.group(1)) if title_match else ""
    if not name:
        return None

    sections = _split_sections(text)
    # 只用「计算」段 (带用量); 「必备原料和工具」混了锅碗瓢盆, 不拿来当食材
    ingredient_lines = _bullet_lines(sections.get("计算", ""))

    ingredients: List[IngredientRecord] = []
    seen = set()
    for line in ingredient_lines:
        record = parse_ingredient_line(line)
        if record and record.name not in seen:
            seen.add(record.name)
            ingredients.append(record)
        if len(ingredients) >= MAX_INGREDIENTS_PER_RECIPE:
            break

    oper_block = sections.get("操作", "")
    steps = []
    for line in oper_block.splitlines():
        if re.match(r"^\s*\d+[.)]", line.strip()) or line.strip().startswith(("*", "-")):
            steps.append(line)
    if not steps:
        steps = [line for line in oper_block.splitlines() if line.strip()]

    tips = _bullet_lines(sections.get("附加内容", ""))

    calories = _to_int(_extract_number(_labeled_value(text, "预估卡路里")))
    cook_minutes = _to_int(_extract_number(_labeled_value(text, "预估烹饪时间")))
    difficulty = map_difficulty(_labeled_value(text, "预估烹饪难度"))

    return RecipeRecord(
        name=name,
        cuisine=HOWTOCOOK_CATEGORIES.get(category, category or None),
        difficulty=difficulty,
        cook_minutes=cook_minutes,
        calories=calories,
        steps=compose_steps(steps, tips),
        source="howtocook",
        ingredients=ingredients,
        sources={"howtocook"},
    )


def _to_int(value: Optional[float]) -> Optional[int]:
    return int(value) if value is not None else None


def record_from_raw(source: str, payload: object) -> Optional[RecipeRecord]:
    if source == "proj_kitchen" and isinstance(payload, dict):
        return parse_proj_kitchen(payload)
    if source == "howtocook" and isinstance(payload, dict):
        return parse_howtocook(payload)
    return None


def _merge_into(target: RecipeRecord, extra: RecipeRecord) -> None:
    """用 extra 补齐 target 的缺失字段 (不覆盖已有值)"""
    for key in ("cuisine", "difficulty", "cook_minutes", "calories", "protein_g", "carb_g", "fat_g"):
        if getattr(target, key) is None and getattr(extra, key) is not None:
            setattr(target, key, getattr(extra, key))
    if not target.steps and extra.steps:
        target.steps = extra.steps
    if not target.ingredients and extra.ingredients:
        target.ingredients = extra.ingredients
    target.sources |= extra.sources


def merge_records(records: Iterable[RecipeRecord]) -> List[RecipeRecord]:
    """按菜名去重合并; 先处理 proj.kitchen (结构更整齐), HowToCook 负责补营养/时间"""
    merged: Dict[str, RecipeRecord] = {}
    for record in records:
        key = record.name
        if key in merged:
            _merge_into(merged[key], record)
        else:
            merged[key] = record
    for record in merged.values():
        record.source = "proj_kitchen" if "proj_kitchen" in record.sources else "howtocook"
    return list(merged.values())
