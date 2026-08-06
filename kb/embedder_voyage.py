# -*- coding: utf-8 -*-
"""
Voyage Embedder（kb_embedder_voyage.py）
=========================================

**依赖**：无第三方 SDK（走 `http_utils.AsyncHTTPClient`）。
Voyage API：`POST {api_base}/v1/embeddings`，OpenAI-compatible。
"""
from __future__ import annotations

from typing import Any

from ..http_utils import AsyncHTTPClient
from .embedder_base import BaseEmbedder

__all__ = ["VoyageEmbedder"]


class VoyageEmbedder(BaseEmbedder):
    """Voyage 嵌入器（voyage-3 / voyage-3-lite / voyage-large-2 等）。"""
    client_name = "voyage"

    def _init_client(self) -> Any:
        import httpx
        http = httpx.AsyncClient(
            base_url=self.config.api_base,
            timeout=self.config.timeout,
        )
        return AsyncHTTPClient(client=http, default_timeout=self.config.timeout)

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        resp = await self._client.apost(
            "/v1/embeddings",
            json={
                "input": batch,
                "model": self.config.model,
                "input_type": "document",
                "encoding_format": "float",
            },
            headers={
                "Authorization": f"Bearer {self.config.resolve_api_key()}",
                **self.config.extra_headers,
            },
        )
        data = resp.json()
        return [d["embedding"] for d in data["data"]]
