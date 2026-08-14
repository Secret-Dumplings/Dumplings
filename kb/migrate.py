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
5. swap：Knowledge.config 指向新 collection + embedder/embed_dim 更新 + 持久化
6. 删除旧 collection

**事务保证**：
- 步骤 5 失败：KB 仍指向旧 collection，数据未丢，可重试
- 步骤 6 失败：旧 collection 残留（幂等 GC）
"""
from __future__ import annotations

import asyncio as _asyncio
import datetime as _dt
import time
from typing import Any

from tangyuanAI.logging_config import get_logger

from .cache import get_global_cache
from .config import EmbedderConfig
from .embedder_factory import create_embedder

__all__ = ["migrate_kb", "migrate_kb_sync", "migrate_embedding_model", "migrate_embedding_model_sync"]


_logger = get_logger("kb.migrate")


def _resolve(kb):
    if isinstance(kb, str):
        from .registry import get_kb
        return get_kb(kb)
    return kb


async def migrate_kb(
    kb,
    new_config: EmbedderConfig,
    *,
    batch_size: int = 100,
) -> dict[str, Any]:
    """切换 KB 嵌入模型。

    Returns:
        {"total_chunks", "duration_sec", "old_collection", "new_collection", "old_embedder"}
    """
    kb = _resolve(kb)
    cfg = kb.config
    if cfg.embedder is None:
        raise ValueError(f"KB {cfg.name!r} has no current embedder; nothing to migrate from")
    if new_config.embed_dim <= 0:
        raise ValueError("new_config.embed_dim must be > 0")

    old_embedder = cfg.embedder
    old_collection = kb.collection
    t0 = time.perf_counter()

    vs = kb.vs

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

    # 5. swap config（重建 config 对象，更新 embedder / embed_dim / collection_name / updated_at）
    new_cfg_data = kb.config.model_dump()
    new_cfg_data["embedder"] = new_config
    new_cfg_data["embed_dim"] = new_config.embed_dim
    new_cfg_data["collection_name"] = new_collection
    new_cfg_data["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    new_cfg = kb.config.__class__(**new_cfg_data)
    kb.config = new_cfg
    kb._sync_mirror()  # 同步实例镜像属性（embed_dim / embedder / 等）
    # 持久化
    kb._meta.save_kb(new_cfg)
    _logger.info(
        f"migrate: KB {cfg.name} embedder → {new_config.provider}/{new_config.model} "
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


def migrate_kb_sync(kb, new_config: EmbedderConfig, **kwargs) -> dict[str, Any]:
    return _asyncio.run(migrate_kb(kb, new_config, **kwargs))


# === 向后兼容（保留原函数名） ===

async def migrate_embedding_model(kb, new_config, **kwargs):
    return await migrate_kb(kb, new_config, **kwargs)


def migrate_embedding_model_sync(kb, new_config, **kwargs):
    return _asyncio.run(migrate_embedding_model(kb, new_config, **kwargs))


