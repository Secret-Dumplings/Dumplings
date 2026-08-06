# -*- coding: utf-8 -*-
"""
Chunker 工厂（kb_chunker_factory.py）
=====================================

**新增 chunker**：在 `kb_chunker_<name>.py` 创建类，在本文件 `_CHUNKERS` dict 加一行。
"""
from __future__ import annotations

from .chunker_html import HTMLChunker
from .chunker_markdown import MarkdownChunker
from .chunker_recursive import RecursiveCharChunker
from .chunker_token import TokenChunker

__all__ = ["create_chunker", "list_chunkers"]


_CHUNKERS = {
    "recursive": RecursiveCharChunker,
    "markdown": MarkdownChunker,
    "token": TokenChunker,
    "html": HTMLChunker,
}


def create_chunker(name: str, *, chunk_size: int = 1024, chunk_overlap: int = 200, **kwargs):
    """创建 chunker 实例。"""
    cls = _CHUNKERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown chunker: {name!r}. Available: {sorted(_CHUNKERS)}"
        )
    return cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)


def list_chunkers() -> list[str]:
    return sorted(_CHUNKERS)
