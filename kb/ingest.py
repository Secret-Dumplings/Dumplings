# -*- coding: utf-8 -*-
"""
文档添加编排（kb_ingest.py）
============================

**职责**：add_document / add_documents —— load → process → chunk → embed → upsert → 写元数据。

**复用**：
- `..kb_loader_factory.create_loader`
- `..kb_chunker_factory.create_chunker`
- `..kb_embedder_factory.create_embedder`
- `..kb_vector_store.QdrantVectorStore`
- `..kb_persistence.KBMetaStore`
- `..kb_cache.get_global_cache`
- `..logging_config.get_logger`
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from typing import Any

from .types import Chunk, DocMeta, KnowledgeBase
from .config import EmbedderConfig
from .loader_factory import create_loader
from .chunker_factory import create_chunker
from .embedder_factory import create_embedder
from .vector_store import QdrantVectorStore
from .persistence import KBMetaStore
from .cache import get_global_cache
from ..logging_config import get_logger


__all__ = [
    "add_document", "add_documents", "add_document_sync", "add_documents_sync",
    "get_vector_store", "shutdown_kb",
]


_logger = get_logger("kb.ingest")

# 向量 store 缓存：key = (location|url) → QdrantVectorStore
_store_cache: dict[str, QdrantVectorStore] = {}
_store_lock = threading.Lock()


def get_vector_store(kb: KnowledgeBase) -> QdrantVectorStore:
    """获取 KB 对应的 VectorStore（按 location/url 缓存，线程安全）。"""
    if kb.qdrant_url:
        key = f"server:{kb.qdrant_url}"
    else:
        key = f"embedded:{kb.qdrant_location}"
    with _store_lock:
        vs = _store_cache.get(key)
        if vs is None:
            vs = QdrantVectorStore(
                location=None if kb.qdrant_url else kb.qdrant_location,
                url=kb.qdrant_url,
                api_key=kb.qdrant_api_key,
                enable_sparse=True,
            )
            _store_cache[key] = vs
        return vs


def shutdown_kb() -> None:
    """关闭所有缓存的 Qdrant client（应用退出时调用，避免资源泄漏）。"""
    import asyncio as _aio
    with _store_lock:
        stores = list(_store_cache.values())
        _store_cache.clear()
    for vs in stores:
        try:
            _aio.run(vs.close())
        except Exception:
            pass


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


async def _ingest_document(
    kb: KnowledgeBase,
    source: str,
    *,
    loader_name: str,
    text: str,
    meta: dict[str, Any],
    store: KBMetaStore,
) -> tuple[str, int]:
    """单文档 ingest：chunk → embed → upsert → 元数据。返回 (doc_id, chunk_count)。"""
    chunker = create_chunker(kb.chunker, chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap)
    chunks: list[Chunk] = chunker.split(text, meta={**meta, "source": source})

    if not chunks:
        _logger.warning(f"empty document after chunking: {source}")
        return "", 0

    # embed
    if kb.embedder is not None:
        embedder = create_embedder(kb.embedder, cache=get_global_cache())
        vectors = await embedder.embed_batch([c.text for c in chunks])
    else:
        # 无 embedder：不能向量检索。抛错（KB 需要 embedder）
        raise ValueError(
            f"KB {kb.name!r} has no embedder. Set kb.embedder to enable document indexing."
        )

    # upsert
    doc_id = uuid.uuid4().hex
    collection = kb.collection_name or kb.id
    vs = get_vector_store(kb)
    await vs.create_collection(collection, dim=kb.embed_dim, enable_quantization=True)
    payloads = [
        {
            "text": c.text,
            "doc_id": doc_id,
            "chunk_id": c.id,
            "source": source,
            "ordinal": c.ordinal,
            "meta": c.meta,
            "visibility": kb.visibility.value,
        }
        for c in chunks
    ]
    await vs.upsert(collection, [c.id for c in chunks], vectors, payloads)

    # 元数据
    store.add_doc(DocMeta(
        id=doc_id,
        kb_id=kb.id,
        source=source,
        loader=loader_name,
        doc_processor=kb.doc_processor,
        content_hash=_content_hash(text),
        chunk_count=len(chunks),
        meta={"visibility": kb.visibility.value},
    ))

    _logger.info(f"doc added: kb={kb.name} doc_id={doc_id} chunks={len(chunks)} source={source}")
    return doc_id, len(chunks)


async def add_document(
    kb_id_or_name: str,
    source: str | list[str],
    *,
    doc_processor: str | None = None,
    loader: str | None = None,
    meta: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> list[str]:
    """添加单个文档（或一批 source）到 KB。返回 doc_ids。

    Args:
        kb_id_or_name: KB 名或 id
        source: 文件路径 / URL / 目录（list 时逐个添加）
        doc_processor: 文档处理服务商（覆盖 KB 配置）
        loader: loader 类型（file / url / directory / raw）
        meta: 附加元数据
        raw_text: 内存文本（直接入 KB）
    """
    from .registry import get_kb as _get_kb

    kb = _get_kb(kb_id_or_name)
    store = KBMetaStore(kb.base_dir)

    # 批量
    sources = source if isinstance(source, list) else [source]

    # 预检查 content-hash 去重（需要读文件，逐个处理）
    doc_ids: list[str] = []
    for s in sources:
        # 用 loader 读
        ldr = create_loader(s, raw_text=raw_text)
        documents = ldr.load(s)

        for doc in documents:
            # content-hash 去重
            chash = _content_hash(doc.text)
            if store.has_doc_with_hash(kb.id, chash):
                _logger.info(f"doc skipped (duplicate content): {s}")
                existing = store.find_doc_by_hash(kb.id, chash)
                if existing:
                    doc_ids.append(existing.id)
                continue

            dmeta = dict(doc.meta)
            if meta:
                dmeta.update(meta)
            did, _ = await _ingest_document(
                kb, doc.source,
                loader_name=ldr.name, text=doc.text, meta=dmeta, store=store,
            )
            if did:
                doc_ids.append(did)
    return doc_ids


async def add_documents(
    kb_id_or_name: str,
    sources: list[str],
    *,
    doc_processor: str | None = None,
    concurrency: int = 8,
) -> dict[str, Any]:
    """批量并发添加文档。

    Args:
        kb_id_or_name: KB 名或 id
        sources: 文件 / URL / 目录列表
        concurrency: 并发度

    Returns:
        {"success": [doc_ids], "failed": [(source, error)]}
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(src: str) -> tuple[bool, str | list[str]]:
        async with sem:
            try:
                dids = await add_document(kb_id_or_name, src, doc_processor=doc_processor)
                return (True, dids)
            except Exception as e:
                _logger.error(f"add_documents failed: source={src}, error={e}")
                return (False, str(e))

    results = await asyncio.gather(*[_one(s) for s in sources])
    success: list[str] = []
    failed: list[tuple[str, str]] = []
    for src, (ok, payload) in zip(sources, results):
        if ok:
            success.extend(payload)  # type: ignore[arg-type]
        else:
            failed.append((src, payload))  # type: ignore[arg-type]
    return {"success": success, "failed": failed}


def add_document_sync(
    kb_id_or_name: str,
    source: str | list[str],
    **kwargs,
) -> list[str]:
    """同步包装 add_document。"""
    return asyncio.run(add_document(kb_id_or_name, source, **kwargs))


def add_documents_sync(
    kb_id_or_name: str,
    sources: list[str],
    **kwargs,
) -> dict[str, Any]:
    """同步包装 add_documents。"""
    return asyncio.run(add_documents(kb_id_or_name, sources, **kwargs))