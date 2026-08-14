# -*- coding: utf-8 -*-
"""
KB 全局注册表（kb/registry.py）
================================

**薄包装**：以 Knowledge 实例为单位存到模块级 dict，向后兼容 `register_kb/get_kb/list_kbs/delete_kb` API。

**新代码推荐用 `Knowledge` 类直接构造**（多实例 + 隔离）；这里的全局 dict 是为了旧 API 兼容。
"""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Optional

from tangyuanAI.logging_config import get_logger

from .types import KnowledgeBase

if TYPE_CHECKING:
    from .knowledge import Knowledge
    from .persistence import KBMetaStore

__all__ = ["register_kb", "get_kb", "list_kbs", "delete_kb", "load_kb", "shutdown_all"]


_logger = get_logger("kb.registry")

# 全局注册表：name → Knowledge 实例
_kbs: dict[str, "Knowledge"] = {}
_kb_lock = threading.RLock()
# 持久化 store 缓存：base_dir → KBMetaStore
_store_cache: dict[str, "KBMetaStore"] = {}


def _store_for(base_dir: str) -> "KBMetaStore":
    """按 base_dir 获取持久化 store（线程安全缓存）。"""
    from pathlib import Path

    from .persistence import KBMetaStore
    key = str(Path(base_dir).expanduser().resolve())
    with _kb_lock:
        st = _store_cache.get(key)
        if st is None:
            st = KBMetaStore(key)
            _store_cache[key] = st
        return st


def _resolve_kb(kb: "Knowledge | str") -> "Knowledge":
    """把 Knowledge 实例或 name 字符串统一解析成实例。"""
    if isinstance(kb, str):
        return get_kb(kb)
    return kb


# === 主 API（向后兼容 + 走 Knowledge 实例） ===

def register_kb(name: str, **overrides) -> "Knowledge":
    """注册一个 KB。

    Args:
        name: KB 名称（唯一）
        **overrides: 覆盖类属性的字段（embedder / reranker / chunk_size / ...）

    Returns: Knowledge 实例
    """
    from .knowledge import Knowledge
    with _kb_lock:
        overwrite = overrides.pop("overwrite", False)
        if name in _kbs and not overwrite:
            raise ValueError(
                f"KB {name!r} already exists. Use overwrite=True to replace it, "
                "or delete_kb() first."
            )
        kb = Knowledge(name, **overrides)
        _kbs[name] = kb
        _logger.info(f"KB registered: name={name} id={kb.id} (via Knowledge class)")
        return kb


def _scan_store_dirs(base_dir: str) -> list[str]:
    """扫出 base_dir 下所有可能的 KB store 目录（含顶层 + 嵌套 `<name>__<id8>/`）。"""
    from pathlib import Path
    dirs: list[str] = [base_dir]
    p = Path(base_dir).expanduser()
    if p.is_dir():
        for sub in sorted(p.glob("*__*/kb_meta.db")):
            dirs.append(str(sub.parent))
        for sub in sorted(p.glob("*/kb_meta.db")):
            if str(sub.parent) not in dirs:
                dirs.append(str(sub.parent))
    return dirs


def get_kb(name_or_id: str) -> "Knowledge":
    """按 name 或 id 查 KB。不在内存 → 从持久化恢复。"""
    with _kb_lock:
        kb = _kbs.get(name_or_id)
        if kb is not None:
            return kb
        for k, v in _kbs.items():
            if v.id == name_or_id:
                return v

    # 从持久化恢复（扫候选 base_dir + 嵌套 KB store）
    candidate_dirs = {kb.base_dir for kb in list(_kbs.values())}
    candidate_dirs.add(os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs"))
    for d in candidate_dirs:
        for store_dir in _scan_store_dirs(d):
            try:
                kb = _load_kb_from_store(name_or_id, store_dir)
            except Exception:
                continue
            if kb is not None:
                with _kb_lock:
                    _kbs[kb.name] = kb
                return kb

    raise KeyError(
        f"KB {name_or_id!r} not found. Registered: {sorted(_kbs)}"
    )


def list_kbs() -> list["Knowledge"]:
    """列出所有 KB（内存 + 持久化合并，按 created_at 排序）。"""
    with _kb_lock:
        in_mem = list(_kbs.values())
    seen = {kb.id: kb for kb in in_mem}
    for d in {kb.base_dir for kb in in_mem} | {os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs")}:
        for store_dir in _scan_store_dirs(d):
            try:
                for config in _store_for(store_dir).list_kbs():
                    if config.id in seen:
                        continue
                    inst = _instantiate_from_config(config, store_dir)
                    if inst is not None:
                        seen[inst.id] = inst
            except Exception:
                continue
    return sorted(seen.values(), key=lambda k: k.config.created_at)


def delete_kb(name_or_id: str) -> bool:
    """删除 KB（内存 + 持久化）。向量数据由调用方决定是否清理。"""
    with _kb_lock:
        kb = _kbs.pop(name_or_id, None) or next(
            (v for k, v in _kbs.items() if v.id == name_or_id), None
        )
        if kb is not None:
            try:
                kb._meta.delete_kb(kb.id)
            except Exception:
                pass
            _logger.info(f"KB deleted: {name_or_id}")
            return True
        # 从持久化扫（候选 base_dir + 嵌套 store）
        for d in {os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs")}:
            for store_dir in _scan_store_dirs(d):
                try:
                    if _store_for(store_dir).delete_kb(name_or_id):
                        _logger.info(f"KB deleted (persistence): {name_or_id}")
                        return True
                except Exception:
                    continue
        return False


def load_kb(name_or_id: str, base_dir: str | None = None) -> "Knowledge":
    """从持久化恢复 KB 实例（公开 API）。"""
    return get_kb(name_or_id)


def shutdown_all() -> None:
    """关闭所有内存中的 Knowledge 实例（释放 Qdrant 客户端）。应用退出时调用。"""
    import asyncio as _aio
    with _kb_lock:
        instances = list(_kbs.values())
    for inst in instances:
        if not inst._closed:
            try:
                _aio.run(inst.shutdown())
            except Exception:
                pass
    _kbs.clear()


def _load_kb_from_store(name_or_id: str, store_dir: str) -> Optional["Knowledge"]:
    """从指定 store 目录的 KBMetaStore 恢复 KB。"""
    config = _store_for(store_dir).load_kb(name_or_id)
    if config is None:
        return None
    return _instantiate_from_config(config, store_dir)


def _instantiate_from_config(config: KnowledgeBase, store_dir: str) -> Optional["Knowledge"]:
    """从 KnowledgeBase config 重建 Knowledge 实例（不重新持久化）。"""
    from .knowledge import Knowledge
    try:
        inst = Knowledge.__new__(Knowledge)
        inst.config = config
        inst.id = config.id
        inst.name = config.name
        # meta store 路径 = 该 KB 自己的 store 目录
        from .persistence import KBMetaStore
        inst._meta = KBMetaStore(store_dir)
        inst._vs = None
        inst._vs_lock = threading.Lock()
        inst._closed = False
        return inst
    except Exception as e:
        _logger.warning(f"failed to instantiate KB from config: {e}")
        return None
