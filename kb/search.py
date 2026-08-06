# -*- coding: utf-8 -*-
"""
搜索编排（kb_search.py）
========================

**流程**：embed query → hybrid search（Qdrant RRF）→ 可选 rerank → threshold → 组装 SearchResult。

**复用**：
- `..kb_embedder_factory.create_embedder`
- `..kb_reranker_factory.create_reranker`
- `..kb_ingest.get_vector_store`
- `..kb_types.SearchResult` / `ScoreKind`
- `..logging_config.get_logger`
"""
from __future__ import annotations

import time
from typing import Any

from .types import Chunk, KnowledgeBase, ScoreKind, SearchResult
from .config import EmbedderConfig
from .embedder_factory import create_embedder
from .reranker_factory import create_reranker
from .cache import get_global_cache
from .ingest import get_vector_store
from ..logging_config import get_logger


__all__ = ["search", "search_sync", "list_documents"]


_logger = get_logger("kb.search")


async def search(
    kb_id_or_name: str,
    query: str,
    *,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    threshold: float | None = None,
    filter_: dict[str, Any] | None = None,
) -> list[SearchResult]:
    """搜索 KB。返回 list[SearchResult]（按 score 降序）。

    Args:
        kb_id_or_name: KB 名或 id
        query: 查询文本
        top_k: 返回条数（默认 kb.top_k）
        use_rerank: 是否重排（None = 跟随 kb.reranker 配置）
        threshold: 匹配度阈值（None = 跟随 kb.threshold；仅对 rerank 分数生效）
        filter_: payload 过滤（如 {"visibility": "public"}）
    """
    from .registry import get_kb as _get_kb

    kb = _get_kb(kb_id_or_name)
    t0 = time.perf_counter()
    k = top_k or kb.top_k
    thr = kb.threshold if threshold is None else threshold

    if kb.embedder is None:
        raise ValueError(
            f"KB {kb.name!r} has no embedder. Set kb.embedder to enable search."
        )

    # 1. embed query
    embedder = create_embedder(kb.embedder, cache=get_global_cache())
    query_vec = await embedder.embed(query)

    # 2. hybrid search（over-fetch）
    over_fetch = min(k * 5, 200)
    collection = kb.collection_name or kb.id
    vs = get_vector_store(kb)
    hits = await vs.search(collection, query_vec, query, top_k=over_fetch, filter_=filter_)

    # 3. 组装候选 chunks
    candidates: list[Chunk] = []
    cosine_scores: dict[str, float] = {}
    bm25_scores: dict[str, float] = {}
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
        bm25_scores[chunk_id] = None  # RRF 分数没有独立 bm25

    if not candidates:
        return []

    # 4. rerank
    rerank_config = kb.reranker
    do_rerank = use_rerank if use_rerank is not None else (
        rerank_config is not None and rerank_config.provider != "no-op"
    )
    rerank_scores: dict[str, float] = {}
    if do_rerank and rerank_config is not None:
        reranker = create_reranker(rerank_config, cache=get_global_cache())
        reranked = await reranker.rerank(query, candidates, top_k=k)
        for c, s in reranked:
            rerank_scores[c.id] = s

    # 5. 组装最终结果
    results: list[SearchResult] = []
    if do_rerank and rerank_scores:
        for c, s in reranked:  # type: ignore[possibly-undefined]
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

    # 截到 k
    results = results[:k]
    _logger.debug(
        f"search: kb={kb.name} query={query[:50]!r} candidates={len(candidates)} "
        f"results={len(results)} took={(time.perf_counter() - t0) * 1000:.1f}ms"
    )
    return results


def search_sync(
    kb_id_or_name: str,
    query: str,
    **kwargs,
) -> list[SearchResult]:
    """同步包装 search。"""
    import asyncio
    return asyncio.run(search(kb_id_or_name, query, **kwargs))


async def list_documents(kb_id_or_name: str) -> list[dict[str, Any]]:
    """列出 KB 的文档（元数据，不返回向量）。"""
    from .registry import get_kb as _get_kb
    from .persistence import KBMetaStore

    kb = _get_kb(kb_id_or_name)
    store = KBMetaStore(kb.base_dir)
    docs = store.list_docs(kb.id)
    return [d.model_dump() for d in docs]


def list_documents_sync(kb_id_or_name: str) -> list[dict[str, Any]]:
    """同步包装 list_documents。"""
    import asyncio
    return asyncio.run(list_documents(kb_id_or_name))