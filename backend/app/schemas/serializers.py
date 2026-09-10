"""ORM 字段的序列化辅助 - 把 JSON 字符串列还原成数组"""
from __future__ import annotations

import json
from typing import Any, List, Optional


def json_list(value: Any) -> List[str]:
    """把 JSON 数组字符串/列表统一成 list[str]"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [text]
    return []


def dumps_list(values: Optional[List[str]]) -> Optional[str]:
    """把数组写入 JSON 字符串列"""
    if values is None:
        return None
    return json.dumps(list(values), ensure_ascii=False)
