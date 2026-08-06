# -*- coding: utf-8 -*-
"""
Cohere 重排器（kb_reranker_cohere.py）
======================================

**依赖**：`cohere>=5.5`（optional dep `[kb-rerank-cohere]`）。
"""
from __future__ import annotations

from typing import Any

from .kb_reranker_base import BaseReranker
from .kb_config import RerankerConfig
from .kb_types import Chunk


__all__ = ["CohereReranker"]


class CohereReranker(BaseReranker):
    """Cohere 重排器。"""
    client_name = "cohere-rerank"

    def _init_model(self) -> Any:
        try:
            import cohere
        except ImportError as e:
            raise ImportError(
                "cohere SDK not installed. Run `pip install tangyuanAI[kb-rerank-cohere]`."
            ) from e
        return cohere.AsyncClient(
            api_key=self.config.resolve_api_key(),
            base_url=self.config.api_base,
        )

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        resp = await self._client.rerank(
            query=query,
            documents=[c.text for c in chunks],
            model=self.config.model,
            top_n=len(chunks),
            return_documents=False,
        )
        # cohere v5: resp.results = [RerankResult(index, relevance_score)]
        scored: list[tuple[Chunk, float]] = []
        for r in resp.results:
            i = int(r.index)
            if 0 <= i < len(chunks):
                scored.append((chunks[i], float(r.relevance_score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored