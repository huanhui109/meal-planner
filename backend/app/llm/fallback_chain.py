"""LLM 多级降级链 - 直接尝试调用, 失败即降级 (不做额外探测请求)"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.llm.base import AllLLMProvidersExhaustedError, LLMClient
from app.llm.openai_client import OpenAICompatibleClient

logger = logging.getLogger(__name__)


class FallbackChain(LLMClient):
    """按顺序尝试各提供商, 第一个成功的即返回"""

    def __init__(self, clients: List[LLMClient]):
        super().__init__(name="fallback-chain")
        self.clients = clients
        self._last_used: Optional[str] = None

    @property
    def last_used(self) -> Optional[str]:
        return self._last_used

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        if not self.clients:
            raise AllLLMProvidersExhaustedError(NO_PROVIDER_MESSAGE)
        last_error: Optional[Exception] = None
        for client in self.clients:
            try:
                content = await client.chat(messages, temperature, max_tokens)
                self._last_used = client.name
                if client is not self.clients[0]:
                    logger.warning("已降级使用 LLM 提供商: %s", client.name)
                return content
            except Exception as exc:  # noqa: BLE001 - 逐级降级需要吞掉任意异常
                last_error = exc
                logger.warning("LLM 提供商 %s 调用失败: %s", client.name, exc)
                continue
        raise AllLLMProvidersExhaustedError(
            f"全部 {len(self.clients)} 个 LLM 提供商均失败, 最后错误: {last_error}"
        )

    async def is_available(self) -> bool:
        for client in self.clients:
            if await client.is_available():
                return True
        return False


NO_PROVIDER_MESSAGE = (
    "未配置任何 LLM 提供商: 请至少设置一个 API Key (GLM4_API_KEY / QWEN_API_KEY / DEEPSEEK_API_KEY), "
    "或启用本地模型, 或设置 APP__LLM__DEMO=true 使用本地演示模式"
)


def build_fallback_chain(settings) -> FallbackChain:
    """根据配置构建降级链: GLM-4 -> Qwen-Max -> DeepSeek -> 本地模型"""
    if settings.llm.demo_mode:
        from app.llm.demo_client import DemoLLMClient

        logger.warning("已启用本地演示 LLM (APP__LLM__DEMO=true), 生成结果固定且不联网")
        return FallbackChain(clients=[DemoLLMClient()])

    clients: List[LLMClient] = []

    if settings.llm.primary.name and settings.llm.primary.api_key:
        clients.append(
            OpenAICompatibleClient(
                name=settings.llm.primary.name,
                api_key=settings.llm.primary.api_key,
                api_base=settings.llm.primary.api_base,
                model=settings.llm.primary.model,
                max_tokens=settings.llm.primary.max_tokens,
            )
        )

    for provider in settings.llm.fallbacks:
        if provider.name and provider.api_key:
            clients.append(
                OpenAICompatibleClient(
                    name=provider.name,
                    api_key=provider.api_key,
                    api_base=provider.api_base,
                    model=provider.model,
                    max_tokens=provider.max_tokens,
                )
            )

    if settings.llm.local.enabled:
        from app.llm.local_client import MLXLocalClient

        clients.append(
            MLXLocalClient(
                model_path=settings.llm.local.model_path,
                port=settings.llm.local.server_port,
            )
        )

    return FallbackChain(clients=clients)
