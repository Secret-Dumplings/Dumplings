# -*- coding: utf-8 -*-
"""
OpenAI / OpenAI-compatible Embedder（kb/embedder_openai.py）
============================================================

**完全自建 httpx 适配**（不用 OpenAI SDK），支持任何 OpenAI 兼容端点：
- `openai`：OpenAI 官方（api_base 默认 https://api.openai.com/v1）
- `openai-compatible`：SiliconFlow / Ollama / vLLM / Xinference / LM Studio / 私网关

**请求约定**：
- 端点：`POST {api_base}/embeddings`（base_url 由用户含 `/v1`）
- 鉴权：`Authorization: Bearer <api_key>`
- 请求体：`{model, input: list[str], encoding_format: "float"}`
- 响应：`{"data": [{"embedding": [...]}, ...]}`
"""
from __future__ import annotations

from typing import Any

from tangyuanAI.http_utils import AsyncHTTPClient

from .embedder_base import BaseEmbedder

__all__ = ["OpenAICompatibleEmbedder"]


def _strip_trailing_slash(url: str) -> str:
    return url.rstrip("/")


class OpenAICompatibleEmbedder(BaseEmbedder):
    """OpenAI / OpenAI-compatible 嵌入器。"""
    client_name = "openai"

    def _init_client(self) -> Any:
        import httpx

        api_base = _strip_trailing_slash(self.config.api_base)
        http = httpx.AsyncClient(
            base_url=api_base,
            timeout=self.config.timeout,
        )
        return AsyncHTTPClient(client=http, default_timeout=self.config.timeout)

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        resp = await self._client.apost(
            "/embeddings",
            json={
                "model": self.config.model,
                "input": batch,
                "encoding_format": "float",
            },
            headers={
                "Authorization": f"Bearer {self.config.resolve_api_key()}",
                **self.config.extra_headers,
            },
        )
        data = resp.json()
        return [d["embedding"] for d in data["data"]]
