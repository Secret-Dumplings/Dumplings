# -*- coding: utf-8 -*-
"""
ColBERT 重排器（kb_reranker_colbert.py）
=========================================

**依赖**：`colbert-ai>=0.2` 或 `pyterrier-colbert`（optional dep `[kb-rerank-local]`）。
**注意**：ColBERT 通常用于 dense retrieval 而不是 reranking；这里提供骨架，
实际接入取决于用户安装的具体 ColBERT 包。

**实现占位**：默认走 sentence-transformers CrossEncoder fallback；
如果用户装了 `colbert-ai`，建议自行扩展。
"""
from __future__ import annotations

import asyncio
from typing import Any

from .reranker_base import BaseReranker
from .config import RerankerConfig
from .types import Chunk


__all__ = ["ColBERTReranker"]


class ColBERTReranker(BaseReranker):
    """ColBERT 重排器（fallback 到 sentence-transformers CrossEncoder）。"""
    client_name = "colbert"

    def _init_model(self) -> Any:
        # 优先用 colbert-ai；如果没装则 fallback
        try:
            from colbert.modeling.checkpoint import Checkpoint  # type: ignore[import-not-found]
            from colbert.modeling.colbert import ColBERT  # type: ignore[import-not-found]
            path = self.config.resolve_model_path()
            ckpt = Checkpoint(name=path, colbert=ColBERT(doc_maxlen=self.config.max_input_tokens))
            return ("colbert-ai", ckpt)
        except ImportError:
            # fallback 到 sentence-transformers
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise ImportError(
                    "Neither colbert-ai nor sentence-transformers installed. "
                    "Run `pip install tangyuanAI[kb-rerank-local]`."
                ) from e
            path = self.config.resolve_model_path()
            return ("st-fallback", CrossEncoder(path, max_length=self.config.max_input_tokens))

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        backend, model = self._client

        if backend == "colbert-ai":
            # 简化：用 text scoring（实际 ColBERT 是 token-level maxsim）
            # 用户如需精确 maxsim，请自行扩展
            texts = [c.text for c in chunks]
            scores = await asyncio.to_thread(model.query, *(query, texts))
            scored = list(zip(chunks, [float(s) for s in (scores if hasattr(scores, "__iter__") else [scores])]))
        else:
            pairs = [(query, c.text) for c in chunks]
            scores = await asyncio.to_thread(model.predict, pairs)
            scored = list(zip(chunks, [float(s) for s in scores]))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored