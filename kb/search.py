# -*- coding: utf-8 -*-
"""
搜索编排（kb_search.py）
========================

**流程**：embed query → hybrid search（Qdrant RRF）→ 可选 rerank → threshold → 组装 SearchResult。

**复用**：
- `..kb_embedder_factory.create_embedder`
- `..kb_reranker_factory.create_reranker`
- `..kb_vector_store.QdrantVectorStore`（通过 Knowledge.vs）
- `..kb_types.SearchResult` / `ScoreKind`
- `..logging_config.get_logger`
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from tangyuanAI.logging_config import get_logger

from .cache import get_global_cache
from .embedder_factory import create_embedder
from .reranker_factory import create_reranker
from .types import Chunk, ScoreKind, SearchResult

__all__ = ["search", "search_sync", "list_documents", "list_documents_sync"]


_logger = get_logger("kb.search")


def _resolve(kb):
    """kb: Knowledge | str → Knowledge 实例。"""
    if isinstance(kb, str):
        from .registry import get_kb
        return get_kb(kb)
    return kb


async def search(
    kb,
    query: str,
    *,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    threshold: float | None = None,
    filter_: dict[str, Any] | None = None,
) -> list[SearchResult]:
    """搜索 KB。返回 list[SearchResult]（按 score 降序）。

    Args:
        kb: Knowledge 实例 或 name 字符串
        query: 查询文本
        top_k: 返回条数（默认 kb.top_k）
        use_rerank: 是否重排（None = 跟随 kb.reranker 配置）
        threshold: 匹配度阈值（None = 跟随 kb.threshold；仅对 rerank 分数生效）
        filter_: payload 过滤（如 {"visibility": "public"}）
    """
    kb = _resolve(kb)
    cfg = kb.config
    t0 = time.perf_counter()
    k = top_k or cfg.top_k
    thr = cfg.threshold if threshold is None else threshold

    if cfg.embedder is None:
        raise ValueError(
            f"KB {cfg.name!r} has no embedder. Set kb.embedder to enable search."
        )

    # 1. embed query
    embedder = create_embedder(cfg.embedder, cache=get_global_cache())
    query_vec = await embedder.embed(query)

    # 2. hybrid search（over-fetch）
    over_fetch = min(k * 5, 200)
    vs = kb.vs
    hits = await vs.search(kb.collection, query_vec, query, top_k=over_fetch, filter_=filter_)

    # 3. 组装候选 chunks
    candidates: list[Chunk] = []
    cosine_scores: dict[str, float] = {}
    for chunk_id, score, payload in hits:
        candidates.append(Chunk(
            id=chunk_id,
            doc_id=payload.get("doc_id", ""),
            ordinal=payload.get("ordinal", 0),
            text=payload.get("text", ""),
            token_count=0,
            meta=payload.get("meta", {}),
        ))
        cosine_scores[chunk_id] = score

    if not candidates:
        return []

    # 4. rerank
    rerank_config = cfg.reranker
    do_rerank = use_rerank if use_rerank is not None else (
        rerank_config is not None and rerank_config.provider != "no-op"
    )
    reranked: list[tuple[Chunk, float]] = []
    if do_rerank and rerank_config is not None:
        reranker = create_reranker(rerank_config, cache=get_global_cache())
        reranked = await reranker.rerank(query, candidates, top_k=k)

    # 5. 组装最终结果
    results: list[SearchResult] = []
    if do_rerank and reranked:
        for c, s in reranked:
            if thr > 0 and s < thr:
                continue
            results.append(SearchResult(
                chunk=c,
                score=s,
                score_type=ScoreKind.RERANK,
                bm25=None,
                cosine=cosine_scores.get(c.id),
                rerank=s,
                rank=len(results),
            ))
    else:
        for idx, c in enumerate(candidates):
            results.append(SearchResult(
                chunk=c,
                score=cosine_scores.get(c.id, 0.0),
                score_type=ScoreKind.COSINE,
                bm25=None,
                cosine=cosine_scores.get(c.id),
                rerank=None,
                rank=idx,
            ))

    results = results[:k]
    _logger.debug(
        f"search: kb={cfg.name} query={query[:50]!r} candidates={len(candidates)} "
        f"results={len(results)} took={(time.perf_counter() - t0) * 1000:.1f}ms"
    )
    return results


def search_sync(kb, query: str, **kwargs) -> list[SearchResult]:
    return asyncio.run(search(kb, query, **kwargs))


async def list_documents(kb) -> list[dict[str, Any]]:
    """列出 KB 的文档元数据。"""
    kb = _resolve(kb)
    docs = kb._meta.list_docs(kb.id)
    return [d.model_dump() for d in docs]


def list_documents_sync(kb) -> list[dict[str, Any]]:
    return asyncio.run(list_documents(kb))
