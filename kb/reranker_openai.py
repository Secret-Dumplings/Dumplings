# -*- coding: utf-8 -*-
"""
OpenAI-compatible 重排器（kb/reranker_openai.py）
==================================================

**用途**：调任何暴露 `/v1/rerank` 端点的服务（vLLM / Cohere-via-proxy / 自家实现 / SiliconFlow）。
"""
from __future__ import annotations

from typing import Any

from ..http_utils import AsyncHTTPClient
from .reranker_base import BaseReranker
from .types import Chunk

__all__ = ["OpenAICompatibleReranker"]


def _normalize_rerank_base(api_base: str) -> str:
    """剥 trailing /v1（避免与路径 `/v1/rerank` 重复）。

    Examples:
        "https://api.siliconflow.cn/v1" -> "https://api.siliconflow.cn"
        "http://localhost:8000"        -> "http://localhost:8000"
        "https://gateway.example.com/v1/" -> "https://gateway.example.com"
    """
    api_base = api_base.rstrip("/")
    if api_base.endswith("/v1"):
        return api_base[:-3]
    return api_base


class OpenAICompatibleReranker(BaseReranker):
    """调 /v1/rerank 端点。

    base_url 兼容 `https://host/v1` 和 `https://host`（自动剥 /v1 防双前缀）。
    """
    client_name = "openai-compatible-rerank"

    def _init_model(self) -> Any:
        import httpx
        api_base = _normalize_rerank_base(self.config.api_base)
        http = httpx.AsyncClient(
            base_url=api_base,
            timeout=self.config.timeout,
        )
        return AsyncHTTPClient(client=http, default_timeout=self.config.timeout)

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        resp = await self._client.apost(
            "/v1/rerank",
            json={
                "query": query,
                "documents": [c.text for c in chunks],
                "model": self.config.model,
                "top_n": len(chunks),
                "return_documents": False,  # SiliconFlow / 大多数实现都接受；不需要原文回传
            },
            headers={
                "Authorization": f"Bearer {self.config.resolve_api_key()}",
                **self.config.extra_headers,
            },
        )
        data = resp.json()
        # 响应形如 {results: [{index, relevance_score, document?}, ...]}
        results = data.get("results") or data.get("data") or []
        scored = sorted(results, key=lambda r: int(r.get("index", 0)))
        out: list[tuple[Chunk, float]] = []
        for r in scored:
            i = int(r.get("index", -1))
            if 0 <= i < len(chunks):
                out.append((chunks[i], float(r.get("relevance_score", 0.0))))
        out.sort(key=lambda x: x[1], reverse=True)
        return out
