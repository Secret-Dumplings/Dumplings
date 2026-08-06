# -*- coding: utf-8 -*-
"""
模型迁移（kb_migrate.py）
=========================

**职责**：切换 KB 的嵌入模型（原子 swap）。

**流程**：
1. 校验 new_config（provider / dim）
2. 读旧 collection 所有 chunks（scroll）
3. 用新 embedder embed_batch（走 cache，命中率高）
4. 写入新 collection（临时）
5. swap：KB.collection_name 指向新 collection + embedder/embed_dim 更新 + 持久化
6. 删除旧 collection

**事务保证**：
- 步骤 5 失败：KB 仍指向旧 collection，数据未丢，可重试
- 步骤 6 失败：旧 collection 残留（幂等 GC）
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from .kb_types import KnowledgeBase
from .kb_config import EmbedderConfig
from .kb_embedder_factory import create_embedder
from .kb_cache import get_global_cache
from .kb_ingest import get_vector_store
from .kb_persistence import KBMetaStore
from .logging_config import get_logger


__all__ = ["migrate_embedding_model", "migrate_embedding_model_sync"]


_logger = get_logger("kb.migrate")


async def migrate_embedding_model(
    kb_id_or_name: str,
    new_config: EmbedderConfig,
    *,
    batch_size: int = 100,
) -> dict[str, Any]:
    """切换 KB 嵌入模型。

    Returns:
        {"total_chunks", "duration_sec", "old_collection", "new_collection", "old_embedder"}
    """
    from .kb_registry import get_kb as _get_kb

    kb = _get_kb(kb_id_or_name)
    if kb.embedder is None:
        raise ValueError(f"KB {kb.name!r} has no current embedder; nothing to migrate from")
    if new_config.embed_dim <= 0:
        raise ValueError("new_config.embed_dim must be > 0")

    old_embedder = kb.embedder
    old_collection = kb.collection_name or kb.id
    t0 = time.perf_counter()

    vs = get_vector_store(kb)

    # 1. 读旧 collection 所有 chunks
    all_points: list[dict[str, Any]] = []
    offset: str | None = None
    while True:
        pts, offset = await vs.scroll(old_collection, limit=1000, offset=offset)
        all_points.extend(pts)
        if offset is None:
            break
    _logger.info(f"migrate: read {len(all_points)} chunks from collection {old_collection}")

    # 2. 建新 collection
    new_collection = f"{kb.id}__{int(t0)}"
    await vs.create_collection(new_collection, dim=new_config.embed_dim, enable_quantization=True)

    if all_points:
        # 3. embed（新模型）
        embedder = create_embedder(new_config, cache=get_global_cache())
        texts = [p.get("text", "") for p in all_points]
        vectors = await embedder.embed_batch(texts)

        # 4. 写新 collection
        ids = [p.get("_id", p.get("id", "")) for p in all_points]
        payloads = [{k: v for k, v in p.items() if k not in ("_id", "id")} for p in all_points]
        await vs.upsert(new_collection, ids, vectors, payloads)
        _logger.info(f"migrate: written {len(vectors)} vectors to {new_collection}")

    # 5. swap config（内存 + 持久化）
    object.__setattr__(kb, "embedder", new_config)
    object.__setattr__(kb, "embed_dim", new_config.embed_dim)
    object.__setattr__(kb, "collection_name", new_collection)
    object.__setattr__(kb, "updated_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    KBMetaStore(kb.base_dir).save_kb(kb)
    _logger.info(
        f"migrate: KB {kb.name} embedder → {new_config.provider}/{new_config.model} "
        f"dim={new_config.embed_dim} collection={new_collection}"
    )

    # 6. 删旧 collection（幂等）
    await vs.drop_collection(old_collection)

    return {
        "total_chunks": len(all_points),
        "duration_sec": time.perf_counter() - t0,
        "old_collection": old_collection,
        "new_collection": new_collection,
        "old_embedder": {
            "provider": old_embedder.provider,
            "model": old_embedder.model,
            "embed_dim": old_embedder.embed_dim,
        },
    }


def migrate_embedding_model_sync(
    kb_id_or_name: str,
    new_config: EmbedderConfig,
    **kwargs,
) -> dict[str, Any]:
    """同步包装 migrate_embedding_model。"""
    import asyncio
    return asyncio.run(migrate_embedding_model(kb_id_or_name, new_config, **kwargs))