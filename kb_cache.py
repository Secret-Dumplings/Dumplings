# -*- coding: utf-8 -*-
"""
Knowledge Base 嵌入缓存层（kb_cache.py）
========================================

**职责**：`EmbeddingCache` Protocol 实现 + 全局缓存实例管理。

**为什么生产环境必备**：
- 重索引 100k 文档 = 100k 次 API 调用 = 几十到几百元
- 调试时反复跑测试，缓存命中省时间省钱
- 切分参数微调时文本 chunk 高度相似，缓存命中率高

**复用**：
- 复用 `..logging_config.get_logger`
- 复用 `..kb_protocols.EmbeddingCache`（Protocol 定义）

**性能预算**：
- 内存命中 ~1μs
- 磁盘命中 ~100μs
- API 调用 ~200ms

**换后端**：将来要换 Redis / Memcached，实现同名接口的类即可。
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import msgpack


def get_logger(name: str):
    from .logging_config import get_logger as _real
    return _real(name)


__all__ = [
    "LRUDiskCache",
    "NullCache",
    "get_global_cache",
    "set_global_cache",
]


# ---------------------------------------------------------------------------
# LRUDiskCache（默认实现）
# ---------------------------------------------------------------------------

class LRUDiskCache:
    """两级缓存：进程内 LRU + 磁盘 SQLite。

    Key：调用方提供（通常是 `sha256(provider|api_base|model|text).hexdigest()`）
    Value：msgpack 压缩的 `list[float]`

    线程安全：`RLock` 保护所有写；读走 SQLite 默认就是线程安全的。
    """
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS embed_cache (
        k        TEXT PRIMARY KEY,
        vec_blob BLOB NOT NULL,
        dim      INTEGER NOT NULL,
        ctime    REAL NOT NULL
    );
    """

    def __init__(
        self,
        *,
        memory_size: int = 10_000,
        db_path: str | Path = "./.tangyuanAI_kbs/embed_cache.db",
    ):
        self._memory_size = int(memory_size)
        self._mem: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._closed = False

        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
            timeout=10.0,
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(self.SCHEMA)

    def _ensure_conn(self) -> None:
        """如果连接被 close 过（如 set_global_cache 换出），懒重开。"""
        if self._closed or self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,
                timeout=10.0,
            )
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(self.SCHEMA)
            self._closed = False

    # === 读 ===

    async def get(self, key: str) -> Optional[list[float]]:
        # 先查内存
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                self._hits += 1
                return self._mem[key]
        # 再查磁盘
        self._ensure_conn()
        row = self._conn.execute(
            "SELECT vec_blob FROM embed_cache WHERE k = ?", (key,)
        ).fetchone()
        if row is None:
            self._misses += 1
            return None
        try:
            vec = msgpack.unpackb(row[0], raw=False)
            if isinstance(vec, list) and vec and isinstance(vec[0], (int, float)):
                vec = [float(v) for v in vec]
        except Exception:
            self._misses += 1
            return None
        # 写回内存（淘汰）
        with self._lock:
            self._mem[key] = vec
            self._mem.move_to_end(key)
            while len(self._mem) > self._memory_size:
                self._mem.popitem(last=False)
        self._hits += 1
        return vec

    # === 写 ===

    async def set(self, key: str, vec: list[float]) -> None:
        with self._lock:
            self._mem[key] = vec
            self._mem.move_to_end(key)
            while len(self._mem) > self._memory_size:
                self._mem.popitem(last=False)
        # 异步写磁盘（同步但很快；msgpack 后几百字节 ~ 几 KB）
        try:
            self._ensure_conn()
            blob = msgpack.packb([float(v) for v in vec], use_bin_type=True)
            self._conn.execute(
                "INSERT INTO embed_cache (k, vec_blob, dim, ctime) VALUES (?, ?, ?, strftime('%s','now')) "
                "ON CONFLICT(k) DO UPDATE SET vec_blob=excluded.vec_blob, dim=excluded.dim, ctime=excluded.ctime",
                (key, blob, len(vec)),
            )
        except Exception as e:
            get_logger("kb.cache").warning(f"cache disk write failed for {key[:8]}...: {e}")

    # === 维护 ===

    async def clear(self) -> None:
        with self._lock:
            self._mem.clear()
            self._hits = 0
            self._misses = 0
        self._ensure_conn()
        self._conn.execute("DELETE FROM embed_cache")

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "memory_entries": len(self._mem),
            "memory_size": self._memory_size,
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        self._closed = True
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = None

    def __repr__(self) -> str:
        return f"LRUDiskCache(memory={len(self._mem)}/{self._memory_size}, db={self.db_path})"


# ---------------------------------------------------------------------------
# NullCache（禁用缓存）
# ---------------------------------------------------------------------------

class NullCache:
    """永远不命中。用于调试或用户明确禁用缓存。"""

    def __init__(self) -> None:
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[list[float]]:
        self._misses += 1
        return None

    async def set(self, key: str, vec: list[float]) -> None:
        pass

    async def clear(self) -> None:
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits, "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "memory_entries": 0, "memory_size": 0,
            "db_path": None,
        }

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return "NullCache()"


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

_global_cache: Any = None
_global_lock = threading.Lock()


def get_global_cache():
    """获取全局缓存实例（懒初始化）。"""
    global _global_cache
    if _global_cache is None:
        with _global_lock:
            if _global_cache is None:
                _global_cache = LRUDiskCache()
    return _global_cache


def set_global_cache(cache) -> None:
    """替换全局缓存实例。"""
    global _global_cache
    with _global_lock:
        old = _global_cache
        _global_cache = cache
    if old is not None and old is not cache:
        try:
            old.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 便捷函数：构造 cache key
# ---------------------------------------------------------------------------

def make_cache_key(
    provider: str,
    api_base: str,
    model: str,
    text: str,
    *,
    dim: int | None = None,
) -> str:
    """构造 cache key。key = sha256(provider|api_base|model|dim|text).hexdigest()。"""
    dim_part = str(dim) if dim is not None else ""
    raw = f"{provider}|{api_base}|{model}|{dim_part}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()