"""F5.1 拍照识别入库 - 让视觉大模型看一眼冰箱

为什么不自己训练模型: 食材识别是通用能力, 视觉大模型已经够用, 而"识别得准不准"
在这个产品里不是关键路径 —— 识别结果只是"填好表单的草稿", 用户确认后才入库。

三个刻意的约束:
  * 不配 Key 就不假装能用: configured=False -> 接口 503, 前端置灰并引导手动添加
  * 图片先等比缩到长边 max_edge_px 再送模型, 手机原图直传既慢又贵
  * caller 可注入: 单测不需要联网, 也不需要真的有 Key
"""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Awaitable, Callable, Dict, List, Optional

from app.config import Settings, get_settings
from app.services.ingredient_amount import normalize_unit

logger = logging.getLogger(__name__)

MAX_ITEMS = 12
CATEGORIES = (
    "蔬菜",
    "肉蛋",
    "水产",
    "豆制品",
    "主食",
    "调味",
    "干货",
    "乳制品",
    "水果",
    "其他",
)

SYSTEM_PROMPT = "你是冰箱食材识别助手。看照片列出能认出的食材, 只输出 JSON, 不要解释、不要 Markdown 代码块。"

USER_PROMPT = """识别这张冰箱/食材照片里的食材, 严格按下面的 JSON 结构输出:
{"items":[{"name":"西红柿","quantity":2,"unit":"个","category":"蔬菜","confidence":0.9,"expiry_days":5}]}

要求:
- name 用中文常用名(写"西红柿"不要写 tomato), 不带数量与修饰
- quantity 是数字, 估不出就填 null, 不要编造
- unit 用 个/根/颗/把/块/袋/盒/瓶/克/毫升 之一
- category 只能是: 蔬菜/肉蛋/水产/豆制品/主食/调味/干货/乳制品/水果/其他
- expiry_days 是"大概还能放几天"的整数, 估不出填 null
- confidence 是 0-1 的小数
- 最多 12 项; 看不清的不要猜
"""

DEMO_RESULT: Dict[str, object] = {
    "items": [
        {
            "name": "西红柿",
            "quantity": 3,
            "unit": "个",
            "category": "蔬菜",
            "confidence": 0.93,
            "expiry_days": 5,
        },
        {
            "name": "鸡蛋",
            "quantity": 6,
            "unit": "个",
            "category": "肉蛋",
            "confidence": 0.96,
            "expiry_days": 12,
        },
        {
            "name": "西蓝花",
            "quantity": 1,
            "unit": "颗",
            "category": "蔬菜",
            "confidence": 0.88,
            "expiry_days": 3,
        },
    ]
}


class VisionError(Exception):
    """识别失败 - 统一转成用户能看懂的文案"""


Caller = Callable[[List[dict]], Awaitable[str]]


class VisionService:
    def __init__(self, settings: Optional[Settings] = None, caller: Optional[Caller] = None):
        self.settings = settings or get_settings()
        self.config = self.settings.llm.vision
        self._caller = caller

    # ---------- 可用性 ----------

    @property
    def resolved_api_key(self) -> str:
        return self.config.api_key or self.settings.llm.primary.api_key

    @property
    def resolved_api_base(self) -> str:
        return self.config.api_base or self.settings.llm.primary.api_base

    @property
    def configured(self) -> bool:
        if not self.config.enabled:
            return False
        if self.settings.llm.demo:
            return True
        return bool(self.resolved_api_key and self.resolved_api_base)

    @property
    def demo(self) -> bool:
        return bool(self.settings.llm.demo)

    # ---------- 主流程 ----------

    async def recognize(self, image: bytes, content_type: str = "") -> dict:
        """识别图片并返回候选食材; 只识别不落库"""
        if not image:
            raise VisionError("图片是空的, 请重新拍一张")
        limit = int(self.config.max_image_mb * 1024 * 1024)
        if len(image) > limit:
            raise VisionError(f"图片超过 {self.config.max_image_mb:g}MB, 请压缩后再试")

        if self.demo:
            return self._result(DEMO_RESULT, degraded=False, note="演示模式: 返回固定识别结果")

        if not self.configured:
            raise VisionError("服务端没有配置视觉模型, 请先手动添加, 或配置视觉模型后再用")

        prepared = self._prepare_image(image)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": prepared}},
                ],
            },
        ]
        caller = self._caller or self._default_caller()
        try:
            raw = await caller(messages)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001 - 上游错误一律转成可读文案
            logger.warning("视觉模型调用失败: %s", exc)
            raise VisionError("识别服务暂时不可用, 请稍后再试或手动添加") from exc

        payload = self._parse(raw)
        return self._result(payload, degraded=False, note="")

    # ---------- 内部 ----------

    def _prepare_image(self, image: bytes) -> str:
        """等比缩放 + 转 JPEG + base64 data URL"""
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可读提示
            raise VisionError("服务端缺少图片处理依赖 (pillow)") from exc

        try:
            with Image.open(io.BytesIO(image)) as handle:
                rgb = handle.convert("RGB")
                rgb.thumbnail((self.config.max_edge_px, self.config.max_edge_px))
                buffer = io.BytesIO()
                rgb.save(buffer, format="JPEG", quality=82, optimize=True)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VisionError("这个文件不像是图片, 请换一张") from exc
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _default_caller(self) -> Caller:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.resolved_api_key,
            base_url=self.resolved_api_base,
            timeout=90.0,
        )

        async def call(messages: List[dict]) -> str:
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.2,
                max_tokens=self.config.max_tokens,
            )
            return response.choices[0].message.content or ""

        return call

    @staticmethod
    def _parse(raw: str) -> dict:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = "\n".join(line for line in text.split("\n") if not line.startswith("```"))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            raise VisionError("识别结果看不懂, 请重试或手动添加") from None

    def _result(self, payload: dict, *, degraded: bool, note: str) -> dict:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raw_items = []
        items: List[dict] = []
        for entry in raw_items[:MAX_ITEMS]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "name": name[:50],
                    "quantity": _as_float(entry.get("quantity")),
                    "unit": normalize_unit(str(entry.get("unit") or ""), "个"),
                    "category": _as_category(entry.get("category")),
                    "confidence": _as_confidence(entry.get("confidence")),
                    "expiry_days": _as_int(entry.get("expiry_days")),
                }
            )
        return {
            "items": items,
            "model": "demo" if self.demo else self.config.model,
            "degraded": degraded,
            "note": note,
        }


def _as_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 100000:
        return None
    return round(number, 3)


def _as_int(value) -> Optional[int]:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _as_confidence(value) -> Optional[float]:
    number = _as_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def _as_category(value) -> str:
    text = str(value or "").strip()
    return text if text in CATEGORIES else "其他"
