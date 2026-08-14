# -*- coding: utf-8 -*-
"""
Jina 重排器（kb_reranker_jina.py）
====================================

**依赖**：无第三方 SDK（走 `http_utils.AsyncHTTPClient`）。
Jina API：`POST {api_base}/v1/rerank`。
"""
from __future__ import annotations

from typing import Any

from tangyuanAI.http_utils import AsyncHTTPClient

from .reranker_base import BaseReranker
from .types import Chunk

__all__ = ["JinaReranker"]


class JinaReranker(BaseReranker):
    """Jina 重排器。"""
    client_name = "jina-rerank"

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
        results = data.get("results") or []
        scored: list[tuple[Chunk, float]] = []
        for r in results:
            i = int(r.get("index", -1))
            if 0 <= i < len(chunks):
                scored.append((chunks[i], float(r.get("relevance_score", 0.0))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
