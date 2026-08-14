# -*- coding: utf-8 -*-
"""
Recursive Character Chunker（kb_chunker_recursive.py）
======================================================

**依赖**：`langchain-text-splitters`（required dep）。
按分隔符递归切分（默认 `["\n\n", "\n", " ", ""]`），保留语义边界。
"""
from __future__ import annotations

from .chunker_base import BaseChunker

__all__ = ["RecursiveCharChunker"]


_DEFAULT_SEPARATORS = ["\n\n", "\n", "。", ". ", " ", ""]


class RecursiveCharChunker(BaseChunker):
    """递归字符切分。"""
    name = "recursive"

    def __init__(self, *, chunk_size: int = 1024, chunk_overlap: int = 200,
                 separators: list[str] | None = None):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError as e:
            raise ImportError(
                "langchain-text-splitters not installed. "
                "Run `pip install tangyuanAI` (it's a required dep)."
            ) from e
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators or _DEFAULT_SEPARATORS,
            keep_separator=True,
        )

    def _split(self, text: str) -> list[str]:
        return self._splitter.split_text(text)
