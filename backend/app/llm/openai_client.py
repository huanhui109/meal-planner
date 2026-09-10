"""OpenAI 兼容客户端 - 支持 GLM-4/Qwen-Max/DeepSeek"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI

from app.llm.base import LLMClient

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMClient):
    """封装 OpenAI SDK, 支持所有 OpenAI 兼容 API"""

    def __init__(
        self,
        name: str,
        api_key: str,
        api_base: str,
        model: str,
        max_tokens: int = 4000,
    ):
        super().__init__(name=name)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=120.0,
        )
        self.model = model
        self.max_tokens = max_tokens

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return response.choices[0].message.content or ""

    async def is_available(self) -> bool:
        """检查 API Key 是否配置且有网络连通性"""
        if not self.client.api_key or self.client.api_key == "":
            return False
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return response.choices is not None and len(response.choices) > 0
        except Exception as e:
            logger.warning(f"LLM provider {self.name} unavailable: {e}")
            return False
