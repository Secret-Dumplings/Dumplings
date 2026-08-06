# -*- coding: utf-8 -*-
"""
HTML Chunker（kb_chunker_html.py）
==================================

**依赖**：`langchain-text-splitters`。
按 HTML 语义（标签层级）切分，保留结构。
"""
from __future__ import annotations

from .kb_chunker_base import BaseChunker


__all__ = ["HTMLChunker"]


class HTMLChunker(BaseChunker):
    """按 HTML 语义切分。"""
    name = "html"

    def __init__(self, *, chunk_size: int = 1024, chunk_overlap: int = 200,
                 headers_to_split_on: list[tuple[str, str]] | None = None):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        try:
            from langchain_text_splitters import HTMLHeaderTextSplitter, RecursiveCharacterTextSplitter
        except ImportError as e:
            raise ImportError(
                "langchain-text-splitters not installed. Run `pip install tangyuanAI`."
            ) from e
        # 保留 h1-h4 结构
        self._html_splitter = HTMLHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on or [
                ("h1", "h1"), ("h2", "h2"), ("h3", "h3"), ("h4", "h4"),
            ]
        )
        self._recursive = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            keep_separator=True,
        )

    def _split(self, text: str) -> list[str]:
        # HTML 需要 <html> 包裹才能被 HTMLHeaderTextSplitter 正确解析
        wrapped = text if text.lstrip().startswith("<") else f"<html><body>{text}</body></html>"
        try:
            header_docs = self._html_splitter.split_text(wrapped)
        except Exception:
            header_docs = []
        if not header_docs:
            return self._recursive.split_text(text)
        out: list[str] = []
        for d in header_docs:
            pieces = self._recursive.split_text(d.page_content)
            out.extend(pieces)
        return out or [text]