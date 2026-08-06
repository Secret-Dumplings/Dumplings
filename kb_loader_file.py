# -*- coding: utf-8 -*-
"""
File Loader（kb_loader_file.py）
================================

**职责**：读本地文件 → 调 DocProcessor 提取文本。

**复用**：
- `..kb_doc_processor_factory.get_processor_for`（按 extension 派发）
- `..kb_loader_base.BaseLoader`
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .kb_loader_base import BaseLoader
from .kb_doc_processor_factory import get_processor_for


__all__ = ["FileLoader"]


class FileLoader(BaseLoader):
    """本地文件加载。"""
    name = "file"

    def can_handle(self, source: str) -> bool:
        return not source.startswith(("http://", "https://", "kb:"))

    def _load(self, source: str) -> list[tuple[str, str, dict[str, Any]]]:
        path = Path(source).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"file not found: {source}")

        processor = get_processor_for(str(path))
        results = processor.process(str(path))
        return [(text, str(path), meta) for text, meta in results]