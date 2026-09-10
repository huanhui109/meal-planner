"""LLM 抽象基类"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class LLMClient(ABC):
    """LLM 客户端抽象基类"""

    def __init__(self, name: str = ""):
        self.name = name

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        """基础对话接口"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """健康检查, 检查 API Key 和网络连通性"""
        ...

    async def chat_with_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> Dict[str, Any]:
        """对话并解析 JSON 响应, 封装常用的 JSON 提取逻辑"""
        import json
        raw = await self.chat(messages, temperature, max_tokens)
        # 尝试提取 JSON 块
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到 JSON 对象
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            raise ValueError(f"LLM 响应无法解析为 JSON: {text[:200]}")


class AllLLMProvidersExhaustedError(Exception):
    """所有 LLM 提供商均不可用"""
    pass
