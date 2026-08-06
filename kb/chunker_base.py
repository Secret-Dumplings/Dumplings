# -*- coding: utf-8 -*-
"""
Knowledge Base 文本切分器抽象基类（kb_chunker_base.py）
=======================================================

**职责**：所有 Chunker 实现共享的公共逻辑（doc_id 生成、token 计数、meta 合并）。

**抽象**（子类必须实现）：
- `_split(text)` → 返回 list[str]（不含 doc_id / meta，由基类包装成 Chunk）

**复用**：
- 复用 `..kb_types.Chunk`
- 复用 `..logging_config.get_logger`
- 第三方：`tiktoken`
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

import tiktoken

from .types import Chunk


def get_logger(name: str):
    from ..logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseChunker"]


class BaseChunker(ABC):
    """所有 Chunker 实现继承此类。

    子类实现 `_split(text)` → list[str]（不含 doc_id / ordinal / token_count / meta）。
    基类负责：doc_id 生成 / ordinal 编号 / token 计数 / meta 合并 / Chunk 构造。
    """

    name: str = "base"

    def __init__(self, *, chunk_size: int = 1024, chunk_overlap: int = 200):
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        try:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    # === 子类实现 ===

    @abstractmethod
    def _split(self, text: str) -> list[str]:
        """纯文本切分；返回 list[str]。"""
        ...

    # === 公共 API ===

    def split(self, text: str, meta: dict[str, Any] | None = None) -> list[Chunk]:
        """包装成 list[Chunk]。

        流程：_split → 编号 → 计 token → 合并 meta → 构造 Chunk
        """
        if not text or not text.strip():
            return []

        doc_id = uuid.uuid4().hex
        base_meta = dict(meta) if meta else {}
        raw_chunks = self._split(text)
        out: list[Chunk] = []
        for i, t in enumerate(raw_chunks):
            if not t or not t.strip():
                continue
            chunk_meta = {**base_meta, "ordinal": i}
            out.append(Chunk(
                id=uuid.uuid4().hex,
                doc_id=doc_id,
                ordinal=i,
                text=t,
                token_count=self._token_count(t),
                meta=chunk_meta,
            ))
        return out

    def _token_count(self, text: str) -> int:
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        return max(1, len(text) // 4)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, size={self.chunk_size}, overlap={self.chunk_overlap})"
