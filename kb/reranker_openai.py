# -*- coding: utf-8 -*-
"""
OpenAI-compatible 重排器（kb_reranker_openai.py）
==================================================

**用途**：调任何暴露 `/v1/rerank` 端点的服务（vLLM / Cohere-via-proxy / 自家实现）。
"""
from __future__ import annotations

from typing import Any

from .reranker_base import BaseReranker
from .config import RerankerConfig
from .types import Chunk
from ..http_utils import AsyncHTTPClient


__all__ = ["OpenAICompatibleReranker"]


class OpenAICompatibleReranker(BaseReranker):
    """调 /v1/rerank 端点。"""
    client_name = "openai-compatible-rerank"

    def _init_model(self) -> Any:
        import httpx
        http = httpx.AsyncClient(
            base_url=self.config.api_base,
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
            },
            headers={
                "Authorization": f"Bearer {self.config.resolve_api_key()}",
                **self.config.extra_headers,
            },
        )
        data = resp.json()
        # 响应形如 {results: [{index, relevance_score}, ...]} 或 {data: [...]}
        results = data.get("results") or data.get("data") or []
        # 按 index 排序
        scored = sorted(results, key=lambda r: r["index"])
        out: list[tuple[Chunk, float]] = []
        for r in scored:
            i = int(r["index"])
            if 0 <= i < len(chunks):
                out.append((chunks[i], float(r.get("relevance_score", 0.0))))
        out.sort(key=lambda x: x[1], reverse=True)
        return out