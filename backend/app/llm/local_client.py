"""mlx_lm 本地推理客户端"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx

from app.llm.base import LLMClient

logger = logging.getLogger(__name__)


class MLXLocalClient(LLMClient):
    """mlx_lm.server 本地推理客户端"""

    def __init__(self, model_path: str = "qwen2.5-7b-instruct-4bit", port: int = 8080):
        super().__init__(name=f"local-{model_path}")
        self.model_path = model_path
        self.port = port
        self.base_url = f"http://localhost:{port}"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                return response.status_code == 200
        except Exception:
            return False
