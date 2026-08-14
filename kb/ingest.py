# -*- coding: utf-8 -*-
"""
文档添加编排（kb/ingest.py）
============================

**职责**：add_document / add_documents —— load → process → chunk → embed → upsert → 写元数据。

**复用**：
- `..kb_loader_factory.create_loader`
- `..kb_chunker_factory.create_chunker`
- `..kb_embedder_factory.create_embedder`
- `..kb_vector_store.QdrantVectorStore`
- `..kb_cache.get_global_cache`
- `..logging_config.get_logger`
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from tangyuanAI.logging_config import get_logger

from .cache import get_global_cache
from .chunker_factory import create_chunker
from .embedder_factory import create_embedder
from .loader_factory import create_loader
from .types import Chunk, DocMeta

__all__ = [
    "add_document", "add_documents", "add_document_sync", "add_documents_sync",
    "shutdown_kb",
]


_logger = get_logger("kb.ingest")


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


async def _ingest_one(
    kb,
    source: str,
    *,
    loader_name: str,
    text: str,
    meta: dict[str, Any],
) -> tuple[str, int]:
    """单文档 ingest：chunk → embed → upsert → 元数据。返回 (doc_id, chunk_count)。"""
    cfg = kb.config
    chunker = create_chunker(cfg.chunker, chunk_size=cfg.chunk_size, chunk_overlap=cfg.chunk_overlap)
    chunks: list[Chunk] = chunker.split(text, meta={**meta, "source": source})

    if not chunks:
        _logger.warning(f"empty document after chunking: {source}")
        return "", 0

    if cfg.embedder is None:
        raise ValueError(
            f"KB {cfg.name!r} has no embedder. Set kb.embedder to enable document indexing."
        )

    embedder = create_embedder(cfg.embedder, cache=get_global_cache())
    vectors = await embedder.embed_batch([c.text for c in chunks])

    import uuid as _uuid
    doc_id = _uuid.uuid4().hex
    vs = kb.vs
    await vs.create_collection(kb.collection, dim=cfg.embed_dim, enable_quantization=True)
    payloads = [
        {
            "text": c.text,
            "doc_id": doc_id,
            "chunk_id": c.id,
            "source": source,
            "ordinal": c.ordinal,
            "meta": c.meta,
            "visibility": cfg.visibility.value,
        }
        for c in chunks
    ]
    await vs.upsert(kb.collection, [c.id for c in chunks], vectors, payloads)

    kb._meta.add_doc(DocMeta(
        id=doc_id,
        kb_id=cfg.id,
        source=source,
        loader=loader_name,
        doc_processor=cfg.doc_processor,
        content_hash=_content_hash(text),
        chunk_count=len(chunks),
        meta={"visibility": cfg.visibility.value},
    ))

    _logger.info(f"doc added: kb={cfg.name} doc_id={doc_id} chunks={len(chunks)} source={source}")
    return doc_id, len(chunks)


async def _do_add(
    kb,
    source: str | list[str],
    *,
    doc_processor: str | None = None,
    meta: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> list[str]:
    """实际 ingest 逻辑（kb 必须是 Knowledge 实例）。"""
    sources = source if isinstance(source, list) else [source]
    doc_ids: list[str] = []
    for s in sources:
        ldr = create_loader(s, raw_text=raw_text)
        documents = ldr.load(s)
        for doc in documents:
            chash = _content_hash(doc.text)
            if kb._meta.has_doc_with_hash(kb.config.id, chash):
                _logger.info(f"doc skipped (duplicate content): {s}")
                existing = kb._meta.find_doc_by_hash(kb.config.id, chash)
                if existing:
                    doc_ids.append(existing.id)
                continue
            dmeta = dict(doc.meta)
            if meta:
                dmeta.update(meta)
            did, _ = await _ingest_one(
                kb, doc.source,
                loader_name=ldr.name, text=doc.text, meta=dmeta,
            )
            if did:
                doc_ids.append(did)
    return doc_ids


# === 模块级 API（向后兼容；接受 Knowledge 实例或 name 字符串） ===

def _resolve(kb):
    """kb: Knowledge | str → Knowledge 实例。"""
    if isinstance(kb, str):
        from .registry import get_kb
        return get_kb(kb)
    return kb


async def add_document(
    kb,
    source: str | list[str],
    *,
    doc_processor: str | None = None,
    meta: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> list[str]:
    """添加文档到 KB。kb 可以是 Knowledge 实例或 name 字符串。"""
    return await _do_add(_resolve(kb), source, doc_processor=doc_processor, meta=meta, raw_text=raw_text)


async def add_documents(
    kb,
    sources: list[str],
    *,
    doc_processor: str | None = None,
    concurrency: int = 8,
) -> dict[str, Any]:
    """批量并发添加。"""
    sem = asyncio.Semaphore(concurrency)

    async def _one(src: str) -> tuple[bool, Any]:
        async with sem:
            try:
                dids = await add_document(kb, src, doc_processor=doc_processor)
                return (True, dids)
            except Exception as e:
                _logger.error(f"add_documents failed: source={src}, error={e}")
                return (False, str(e))

    results = await asyncio.gather(*[_one(s) for s in sources])
    success: list[str] = []
    failed: list[tuple[str, str]] = []
    for src, (ok, payload) in zip(sources, results):
        if ok:
            success.extend(payload)
        else:
            failed.append((src, payload))
    return {"success": success, "failed": failed}


def add_document_sync(kb, source, **kwargs) -> list[str]:
    return asyncio.run(add_document(kb, source, **kwargs))


def add_documents_sync(kb, sources, **kwargs) -> dict[str, Any]:
    return asyncio.run(add_documents(kb, sources, **kwargs))


def shutdown_kb() -> None:
    """关闭所有活跃 KB 的 Qdrant client（应用退出时调用）。"""
    import asyncio as _aio

    try:
        from .knowledge import Knowledge  # noqa
    except ImportError:
        return
    # 遍历所有内存中的 Knowledge 实例
    from .registry import _kbs
    instances = list(_kbs.values())
    for inst in instances:
        if not inst._closed:
            try:
                _aio.run(inst.shutdown())
            except Exception:
                pass
