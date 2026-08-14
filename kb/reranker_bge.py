# -*- coding: utf-8 -*-
"""
BGE 重排器（kb_reranker_bge.py）
=================================

**依赖**：`sentence-transformers>=2.2`（optional dep `[kb-rerank-local]`）。

**模型**：BAAI/bge-reranker-large / BAAI/bge-reranker-v2-m3 / BAAI/bge-reranker-base 等。
Cross-encoder 模型：query + chunk 拼一起打分。
"""
from __future__ import annotations

import asyncio
from typing import Any

from .reranker_base import BaseReranker
from .types import Chunk

__all__ = ["BGEReranker"]


class BGEReranker(BaseReranker):
    """BGE / 任何 sentence-transformers Cross-encoder 重排器。"""
    client_name = "bge-local"

    def _init_model(self) -> Any:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run `pip install tangyuanAI[kb-rerank-local]`."
            ) from e
        path = self.config.resolve_model_path()
        return CrossEncoder(path, max_length=self.config.max_input_tokens)

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        pairs = [(query, c.text) for c in chunks]
        # CrossEncoder.predict 是 sync；用 asyncio.to_thread
        scores = await asyncio.to_thread(self._client.predict, pairs)
        scored = list(zip(chunks, [float(s) for s in scores]))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
