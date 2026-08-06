# -*- coding: utf-8 -*-
"""
Token Chunker（kb_chunker_token.py）
====================================

**依赖**：`langchain-text-splitters` + `tiktoken`。
按 token 数切分（不是字符数），chunk_size = token 数。
"""
from __future__ import annotations

from .chunker_base import BaseChunker


__all__ = ["TokenChunker"]


class TokenChunker(BaseChunker):
    """按 token 数切分（cl100k_base）。"""
    name = "token"

    def __init__(self, *, chunk_size: int = 1024, chunk_overlap: int = 200,
                 model_name: str = "cl100k_base"):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        try:
            from langchain_text_splitters import TokenTextSplitter
        except ImportError as e:
            raise ImportError(
                "langchain-text-splitters not installed. Run `pip install tangyuanAI`."
            ) from e
        self._splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding_name=model_name,
        )

    def _split(self, text: str) -> list[str]:
        return self._splitter.split_text(text)