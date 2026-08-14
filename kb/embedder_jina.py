# -*- coding: utf-8 -*-
"""
Jina Embedder（kb_embedder_jina.py）
=====================================

**依赖**：无第三方 SDK（走 `http_utils.AsyncHTTPClient`）。
Jina 提供 OpenAI-compatible API（`POST {api_base}/v1/embeddings`）。
"""
from __future__ import annotations

from typing import Any

from tangyuanAI.http_utils import AsyncHTTPClient

from .embedder_base import BaseEmbedder

__all__ = ["JinaEmbedder"]


class JinaEmbedder(BaseEmbedder):
    """Jina 嵌入器（jina-embeddings-v3 / jina-embeddings-v2-base-en 等）。"""
    client_name = "jina"

    def _init_client(self) -> Any:
        import httpx
        http = httpx.AsyncClient(
            base_url=self.config.api_base,
            timeout=self.config.timeout,
        )
        return AsyncHTTPClient(client=http, default_timeout=self.config.timeout)

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        # AsyncHTTPClient 已经把 base_url 拼上去了；这里传相对路径
        resp = await self._client.apost(
            "/v1/embeddings",
            json={"input": batch, "model": self.config.model},
            headers={
                "Authorization": f"Bearer {self.config.resolve_api_key()}",
                **self.config.extra_headers,
            },
        )
        data = resp.json()
        return [d["embedding"] for d in data["data"]]
