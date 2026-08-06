# -*- coding: utf-8 -*-
"""
OpenAI / OpenAI-compatible Embedder（kb_embedder_openai.py）
============================================================

**支持的端点**（`provider` 字段）：
- `openai`：OpenAI 官方 API（api_base 默认 https://api.openai.com/v1）
- `openai-compatible`：任何 OpenAI-compatible 端点
  - Ollama：`api_base="http://localhost:11434/v1"`
  - vLLM：`api_base="http://localhost:8000/v1"`
  - Xinference：`api_base="http://localhost:9997/v1"`
  - LM Studio：`api_base="http://localhost:1234/v1"`
  - 私网关：`api_base="https://gateway.example.com/openai/v1"`

**依赖**：`openai>=1.50`（异步客户端 + retries + 默认 base_url）。
"""
from __future__ import annotations

from typing import Any

from .embedder_base import BaseEmbedder

__all__ = ["OpenAICompatibleEmbedder"]


class OpenAICompatibleEmbedder(BaseEmbedder):
    """OpenAI / OpenAI-compatible 嵌入器。"""
    client_name = "openai"

    def _init_client(self) -> Any:
        # 延迟 import：openai 是 required dep（v8 pyproject.toml）
        import openai

        return openai.AsyncOpenAI(
            api_key=self.config.resolve_api_key(),
            base_url=self.config.api_base,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
            default_headers=self.config.extra_headers or None,
        )

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        # openai SDK 已经内置退避重试；max_retries 在客户端初始化时设置
        resp = await self._client.embeddings.create(
            model=self.config.model,
            input=batch,
            encoding_format="float",
        )
        return [d.embedding for d in resp.data]
