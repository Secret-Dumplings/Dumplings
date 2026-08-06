# -*- coding: utf-8 -*-
"""
NoOp 重排器（kb_reranker_noop.py）
==================================

**用途**：默认占位实现，不重排，直接按原顺序返回前 top_k 个。
"""
from __future__ import annotations

from typing import Any

from .reranker_base import BaseReranker
from .config import RerankerConfig
from .types import Chunk


__all__ = ["NoOpReranker"]


class NoOpReranker(BaseReranker):
    """NoOp 重排：原顺序返回前 top_k 个 chunk，分数全 0。"""
    client_name = "noop"

    def _init_model(self) -> Any:
        return None

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        return [(c, 0.0) for c in chunks]