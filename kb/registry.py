# -*- coding: utf-8 -*-
"""
KB 全局注册表（kb_registry.py）
================================

**职责**：进程内 KB 注册 + 元数据持久化同步。

**设计**：
- 内存 dict（name → KnowledgeBase）做快速查找
- 同时写 KBMetaStore（SQLite）做持久化
- RLock 保护并发

**替换**：换存储 = 换 `KBMetaStore` 实现。
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Optional

from .types import KnowledgeBase
from .persistence import KBMetaStore
from ..logging_config import get_logger


__all__ = ["register_kb", "get_kb", "list_kbs", "delete_kb", "_kbs"]


_logger = get_logger("kb.registry")

# 全局注册表：name → KnowledgeBase
_kbs: dict[str, KnowledgeBase] = {}
_kb_lock = threading.RLock()


def _store_for(base_dir: str) -> KBMetaStore:
    """按 base_dir 获取持久化 store（进程内缓存）。"""
    key = str(Path(base_dir).expanduser().resolve())
    with _kb_lock:
        st = _store_cache.get(key)
        if st is None:
            st = KBMetaStore(key)
            _store_cache[key] = st
        return st


_store_cache: dict[str, KBMetaStore] = {}


def register_kb(
    name: str,
    *,
    embedder=None,
    reranker=None,
    top_k: int = 5,
    doc_processor: str = "unstructured",
    chunk_size: int = 1024,
    chunk_overlap: int = 200,
    threshold: float = 0.0,
    base_dir: str | None = None,
    qdrant_location: str = "",
    qdrant_url: str | None = None,
    qdrant_api_key: str | None = None,
    chunker: str = "recursive",
    visibility: str = "private",
    overwrite: bool = False,
    **kwargs,
) -> KnowledgeBase:
    """注册一个 KB（内存 + 持久化）。

    Args:
        name: KB 名称（唯一）
        embedder: EmbedderConfig | None
        reranker: RerankerConfig | None
        top_k: 请求文档片段数
        doc_processor: 文档处理服务商（unstructured / minerU / openminerU / paddleocr / raw）
        chunk_size: 分段大小
        chunk_overlap: 重叠大小
        threshold: 匹配度阈值
        base_dir: 数据目录
        qdrant_location: embedded Qdrant 路径
        qdrant_url / qdrant_api_key: server Qdrant
        chunker: recursive / markdown / token / html
        visibility: private / public
        overwrite: 已存在时是否覆盖
    """
    from .types import Visibility
    import os as _os

    # 默认 base_dir 从 env 读（测试隔离 / 生产配置用）
    if base_dir is None:
        base_dir = _os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs")

    with _kb_lock:
        if name in _kbs and not overwrite:
            raise ValueError(
                f"KB {name!r} already exists. Use overwrite=True to replace it, "
                "or delete_kb() first."
            )

        kb = KnowledgeBase(
            name=name,
            embedder=embedder,
            reranker=reranker,
            top_k=top_k,
            doc_processor=doc_processor,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            threshold=threshold,
            base_dir=base_dir,
            qdrant_location=qdrant_location,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            chunker=chunker,
            visibility=Visibility(visibility),
            **kwargs,
        )

        _kbs[name] = kb
        # 持久化（与 ingest 用同一个 base_dir 的 store，保证 FK 一致）
        store = _store_for(kb.base_dir)
        store.save_kb(kb)
        _logger.info(
            f"KB registered: name={name} id={kb.id} embedder={kb.embedder.model if kb.embedder else None}"
        )
        return kb


def get_kb(name_or_id: str) -> KnowledgeBase:
    """按 name 或 id 查 KB。不在内存 → 尝试从持久化恢复。"""
    with _kb_lock:
        kb = _kbs.get(name_or_id)
        if kb is not None:
            return kb
        # 按 id 查
        for k, v in _kbs.items():
            if v.id == name_or_id:
                return v

    # 从持久化恢复：扫描已缓存的 store + 默认 base_dir + env 配置
    candidate_dirs = {kb.base_dir for kb in list(_kbs.values())}
    candidate_dirs.add("./.tangyuanAI_kbs")
    import os as _os
    candidate_dirs.add(_os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs"))
    for d in candidate_dirs:
        try:
            kb = _store_for(d).load_kb(name_or_id)
        except Exception:
            continue
        if kb is not None:
            with _kb_lock:
                _kbs[kb.name] = kb
            return kb

    raise KeyError(
        f"KB {name_or_id!r} not found. Registered: {sorted(_kbs)}"
    )


def list_kbs() -> list[KnowledgeBase]:
    """列出所有 KB（内存 + 持久化合并）。"""
    with _kb_lock:
        in_mem = list(_kbs.values())
    seen = {kb.id: kb for kb in in_mem}
    # 从缓存 store + 默认 base_dir 补
    for d in [kb.base_dir for kb in in_mem] + ["./.tangyuanAI_kbs"]:
        try:
            for kb in _store_for(d).list_kbs():
                seen.setdefault(kb.id, kb)
        except Exception:
            continue
    return sorted(seen.values(), key=lambda k: k.created_at)


def delete_kb(name_or_id: str) -> bool:
    """删除 KB（内存 + 持久化）。向量数据由调用方决定是否清理。"""
    with _kb_lock:
        kb = None
        if name_or_id in _kbs:
            kb = _kbs.pop(name_or_id)
        else:
            for k, v in _kbs.items():
                if v.id == name_or_id:
                    kb = _kbs.pop(k)
                    break
        if kb is None:
            # 从持久化删（扫描候选 base_dir）
            for d in [k.base_dir for k in _kbs.values()] + ["./.tangyuanAI_kbs"]:
                try:
                    if _store_for(d).delete_kb(name_or_id):
                        _logger.info(f"KB deleted (persistence): {name_or_id}")
                        return True
                except Exception:
                    continue
            return False
        _store_for(kb.base_dir).delete_kb(kb.id)
        _logger.info(f"KB deleted: {name_or_id}")
        return True