# -*- coding: utf-8 -*-
"""
RawText Loader（kb_loader_raw.py）
==================================

**职责**：内存文本加载（`raw_text="..."` 直接入 KB，不落盘）。
**用途**：编程式 API 直接传文本；CLI 的 `--text` 参数。
"""
from __future__ import annotations

from typing import Any

from .loader_base import BaseLoader


__all__ = ["RawTextLoader"]


class RawTextLoader(BaseLoader):
    """内存文本加载。"""
    name = "raw"

    def __init__(self, text: str, *, source: str | None = None):
        self.text = text
        self.source = source or "raw:text"

    def can_handle(self, source: str) -> bool:
        return True  # 直接构造，source 只是标识

    def _load(self, source: str) -> list[tuple[str, str, dict[str, Any]]]:
        return [(self.text, self.source, {"loader": "raw", "text_source": self.source})]