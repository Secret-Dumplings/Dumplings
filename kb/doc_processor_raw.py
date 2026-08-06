# -*- coding: utf-8 -*-
"""
RawText DocProcessor（kb_doc_processor_raw.py）
==============================================

**用途**：直接读文本文件（txt / md / html / json / csv），不做结构化提取。
最轻量，零外部依赖。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .doc_processor_base import BaseDocProcessor


__all__ = ["RawTextProcessor"]


class RawTextProcessor(BaseDocProcessor):
    """直接读文件内容。"""
    name = "raw"
    supported_extensions = (".txt", ".md", ".markdown", ".html", ".htm",
                            ".json", ".csv", ".yaml", ".yml", ".xml", ".log")

    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        p = Path(file_path)
        text = p.read_text(encoding="utf-8", errors="replace")
        return [(text, {"file": str(file_path), "processor": "raw"})]