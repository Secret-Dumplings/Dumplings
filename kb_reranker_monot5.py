# -*- coding: utf-8 -*-
"""
MonoT5 重排器（kb_reranker_monot5.py）
======================================

**依赖**：`sentence-transformers>=2.2` + `torch>=2.0`（optional dep `[kb-rerank-local]`）。

**模型**：castorini/monot5-base-msmarco / monot5-large-msmarco-10k 等。
MonoT5 把 rerank 当成 seq2seq：输入 "Query: q Document: d Relevant:"，输出 "true" / "false"。
"""
from __future__ import annotations

import asyncio
from typing import Any

from .kb_reranker_base import BaseReranker
from .kb_config import RerankerConfig
from .kb_types import Chunk


__all__ = ["MonoT5Reranker"]


class MonoT5Reranker(BaseReranker):
    """MonoT5 重排器（seq2seq True/False → score）。"""
    client_name = "monot5"

    def _init_model(self) -> Any:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run `pip install tangyuanAI[kb-rerank-local]`."
            ) from e
        path = self.config.resolve_model_path()
        # MonoT5 用 CrossEncoder 接口（sentence-transformers 支持）
        return CrossEncoder(path, max_length=self.config.max_input_tokens)

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        pairs = [(query, c.text) for c in chunks]
        # CrossEncoder.predict 返回的是 token logits（"true" vs "false"）
        # 取 "true" 的概率作为 score（sentence-transformers 文档约定）
        scores = await asyncio.to_thread(self._client.predict, pairs)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        # scores 可能是 [[0.1, 0.9], ...]（softmax 后的）或者 [0.9, 0.1, ...]（原始）
        scored: list[tuple[Chunk, float]] = []
        for c, s in zip(chunks, scores):
            if isinstance(s, (list, tuple)) and len(s) >= 2:
                # softmax 形式：取第二列（true 的概率）
                score = float(s[1]) if len(s) > 1 else float(s[0])
            else:
                score = float(s)
            scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored