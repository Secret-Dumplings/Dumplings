# -*- coding: utf-8 -*-
"""
Knowledge Base 持久化层（kb_persistence.py）
============================================

**职责**：KB 配置 + 文档元数据的持久化。单 SQLite 文件（`kb_meta.db`），WAL 模式 + RLock。

**为什么自己写不复用 `persistence.py`**：
- `persistence.py` 是给 Agent 状态用的（保存 conversation history 等）
- KB 持久化是独立领域（KB config + doc metadata + dedup hash）
- 接口相似但数据不同，硬合会污染 `persistence.py` 的语义

**复用**：
- 复用 `..logging_config.get_logger`
- 复用 `..errors.APIError`（运行时抛错）

**换后端**：将来要换 Postgres / MySQL，实现同名接口的类即可（`PostgresMetaStore` / `MySQLMetaStore`）。
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from .types import DocMeta, KnowledgeBase


def get_logger(name: str):
    """本地 logger 包装（避免循环 import）。"""
    from ..logging_config import get_logger as _real
    return _real(name)


__all__ = ["KBMetaStore"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_registry (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    config_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_registry (
    id            TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL,
    source        TEXT NOT NULL,
    loader        TEXT NOT NULL,
    doc_processor TEXT,
    content_hash  TEXT NOT NULL,
    chunk_count   INTEGER NOT NULL,
    meta_json     TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    FOREIGN KEY (kb_id) REFERENCES kb_registry(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_doc_kb ON doc_registry(kb_id);
CREATE INDEX IF NOT EXISTS idx_doc_hash ON doc_registry(content_hash, kb_id);

CREATE TABLE IF NOT EXISTS schema_meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# KBMetaStore
# ---------------------------------------------------------------------------

class KBMetaStore:
    """KB 配置 + 文档元数据持久化。

    线程安全：`threading.RLock` 保护写；读并发（SQLite WAL）。
    进程内多 store 实例 = 多文件（同 base_dir 不要开多个 store 实例）。
    """
    SCHEMA_VERSION = 1

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "kb_meta.db"
        self._lock = threading.RLock()
        self._conn = self._init_conn()
        self._init_schema()
        _log = get_logger("kb.persistence")
        _log.info(f"KBMetaStore opened: {self.db_path}")

    # === 连接 + Schema ===

    def _init_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit；我们用 BEGIN/COMMIT 显式事务
            timeout=10.0,
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO schema_meta (k, v) VALUES (?, ?)",
                ("schema_version", str(self.SCHEMA_VERSION)),
            )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # === KB config ===

    def save_kb(self, kb: KnowledgeBase) -> None:
        """upsert KB 配置。"""
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO kb_registry (id, name, config_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  name=excluded.name, config_json=excluded.config_json, updated_at=excluded.updated_at "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "  id=excluded.id, config_json=excluded.config_json, updated_at=excluded.updated_at",
                    (kb.id, kb.name, kb.model_dump_json(), kb.created_at, now),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def load_kb(self, name_or_id: str) -> Optional[KnowledgeBase]:
        """按 name 或 id 查 KB。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT config_json FROM kb_registry WHERE id = ? OR name = ? LIMIT 1",
                (name_or_id, name_or_id),
            ).fetchone()
            if row is None:
                return None
            try:
                return KnowledgeBase.model_validate_json(row["config_json"])
            except Exception as e:
                get_logger("kb.persistence").error(
                    f"load_kb failed for {name_or_id!r}: {e}"
                )
                return None

    def list_kbs(self) -> list[KnowledgeBase]:
        """列出所有 KB（按 created_at 升序）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT config_json FROM kb_registry ORDER BY created_at"
            ).fetchall()
        out: list[KnowledgeBase] = []
        for row in rows:
            try:
                out.append(KnowledgeBase.model_validate_json(row["config_json"]))
            except Exception as e:
                get_logger("kb.persistence").warning(f"skip invalid KB row: {e}")
        return out

    def delete_kb(self, name_or_id: str) -> bool:
        """按 name 或 id 删除 KB（级联删除 doc_registry）。"""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                cur = self._conn.execute(
                    "DELETE FROM kb_registry WHERE id = ? OR name = ?",
                    (name_or_id, name_or_id),
                )
                self._conn.execute("COMMIT")
                return cur.rowcount > 0
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # === 文档元数据 ===

    def add_doc(self, meta: DocMeta) -> None:
        """upsert 文档元数据。"""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO doc_registry "
                    "(id, kb_id, source, loader, doc_processor, content_hash, chunk_count, meta_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  source=excluded.source, loader=excluded.loader, "
                    "  doc_processor=excluded.doc_processor, chunk_count=excluded.chunk_count, "
                    "  meta_json=excluded.meta_json",
                    (
                        meta.id, meta.kb_id, meta.source, meta.loader, meta.doc_processor,
                        meta.content_hash, meta.chunk_count,
                        json.dumps(meta.meta, ensure_ascii=False), meta.created_at,
                    ),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def has_doc_with_hash(self, kb_id: str, content_hash: str) -> bool:
        """同 KB 内是否有同 content_hash 的文档（dedup 用）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM doc_registry WHERE kb_id = ? AND content_hash = ? LIMIT 1",
                (kb_id, content_hash),
            ).fetchone()
            return row is not None

    def find_doc_by_hash(self, kb_id: str, content_hash: str) -> Optional[DocMeta]:
        """按 content_hash 查 doc_meta（dedup 时复用）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, kb_id, source, loader, doc_processor, content_hash, chunk_count, meta_json, created_at "
                "FROM doc_registry WHERE kb_id = ? AND content_hash = ? LIMIT 1",
                (kb_id, content_hash),
            ).fetchone()
        if row is None:
            return None
        return DocMeta(
            id=row["id"], kb_id=row["kb_id"], source=row["source"],
            loader=row["loader"], doc_processor=row["doc_processor"],
            content_hash=row["content_hash"], chunk_count=row["chunk_count"],
            meta=json.loads(row["meta_json"]) if row["meta_json"] else {},
            created_at=row["created_at"],
        )

    def list_docs(self, kb_id: str) -> list[DocMeta]:
        """列出 KB 的所有文档元数据。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kb_id, source, loader, doc_processor, content_hash, chunk_count, meta_json, created_at "
                "FROM doc_registry WHERE kb_id = ? ORDER BY created_at",
                (kb_id,),
            ).fetchall()
        out: list[DocMeta] = []
        for row in rows:
            out.append(DocMeta(
                id=row["id"], kb_id=row["kb_id"], source=row["source"],
                loader=row["loader"], doc_processor=row["doc_processor"],
                content_hash=row["content_hash"], chunk_count=row["chunk_count"],
                meta=json.loads(row["meta_json"]) if row["meta_json"] else {},
                created_at=row["created_at"],
            ))
        return out

    def delete_doc(self, kb_id: str, doc_id: str) -> bool:
        """按 doc_id 删除文档元数据（不删向量 — 那是 VectorStore 的事）。"""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                cur = self._conn.execute(
                    "DELETE FROM doc_registry WHERE kb_id = ? AND id = ?",
                    (kb_id, doc_id),
                )
                self._conn.execute("COMMIT")
                return cur.rowcount > 0
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def count_docs(self, kb_id: str) -> int:
        """KB 内文档数。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM doc_registry WHERE kb_id = ?",
                (kb_id,),
            ).fetchone()
            return int(row["n"]) if row else 0

    # === 调试 / 维护 ===

    def vacuum(self) -> None:
        """VACUUM；释放空间。"""
        with self._lock:
            self._conn.execute("VACUUM")

    def __repr__(self) -> str:
        return f"KBMetaStore(db={self.db_path})"