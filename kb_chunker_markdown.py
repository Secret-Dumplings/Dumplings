# -*- coding: utf-8 -*-
"""
Markdown Chunker（kb_chunker_markdown.py）
==========================================

**依赖**：`langchain-text-splitters`。
按 Markdown 标题结构切分，保留 heading 层级。
"""
from __future__ import annotations

from .kb_chunker_base import BaseChunker


__all__ = ["MarkdownChunker"]


_HEADER_SPLITTER = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
    ("#####", "h5"),
    ("######", "h6"),
]


class MarkdownChunker(BaseChunker):
    """按 Markdown 标题切分。"""
    name = "markdown"

    def __init__(self, *, chunk_size: int = 1024, chunk_overlap: int = 200,
                 headers_to_split_on: list[tuple[str, str]] | None = None):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
        except ImportError as e:
            raise ImportError(
                "langchain-text-splitters not installed. Run `pip install tangyuanAI`."
            ) from e

        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on or _HEADER_SPLITTER,
            strip_headers=False,
        )
        self._recursive = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            keep_separator=True,
        )

    def _split(self, text: str) -> list[str]:
        # 先按 header 切（保留结构），再对每段按 size 递归切
        header_docs = self._header_splitter.split_text(text)
        if not header_docs:
            return self._recursive.split_text(text)
        out: list[str] = []
        for d in header_docs:
            pieces = self._recursive.split_text(d.page_content)
            if not pieces:
                continue
            out.extend(pieces)
        return out or [text]