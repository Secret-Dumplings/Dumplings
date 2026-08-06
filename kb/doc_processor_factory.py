# -*- coding: utf-8 -*-
"""
DocProcessor 工厂（kb_doc_processor_factory.py）
=================================================

**职责**：按文件扩展名 + 用户偏好派发到具体 DocProcessor。

**新增 processor**：在 `kb_doc_processor_<name>.py` 创建类，在本文件 `DOC_PROCESSOR_CATALOG` dict 加一行。
"""
from __future__ import annotations

from pathlib import Path

from .doc_processor_mineru import MinerUProcessor
from .doc_processor_openmineru import OpenMinerUProcessor
from .doc_processor_paddleocr import PaddleOCRProcessor
from .doc_processor_raw import RawTextProcessor
from .doc_processor_unstructured import UnstructuredProcessor

__all__ = ["get_processor_for", "list_doc_processors", "DOC_PROCESSOR_CATALOG"]


DOC_PROCESSOR_CATALOG: dict[str, type] = {
    "unstructured": UnstructuredProcessor,
    "minerU": MinerUProcessor,
    "openminerU": OpenMinerUProcessor,
    "paddleocr": PaddleOCRProcessor,
    "raw": RawTextProcessor,
}

# 默认派发规则：扩展名 → processor 名字
_EXT_DEFAULT = {
    ".pdf": "unstructured",       # 可指定 minerU / openminerU / paddleocr
    ".png": "paddleocr",
    ".jpg": "paddleocr",
    ".jpeg": "paddleocr",
    ".bmp": "paddleocr",
    ".tiff": "paddleocr",
    ".tif": "paddleocr",
    ".docx": "unstructured",
    ".doc": "unstructured",
    ".pptx": "unstructured",
    ".xlsx": "unstructured",
    ".csv": "raw",
    ".json": "raw",
    ".html": "raw",
    ".htm": "raw",
    ".md": "raw",
    ".markdown": "raw",
    ".txt": "raw",
    ".yaml": "raw",
    ".yml": "raw",
}


def get_processor_for(file_path: str, preferred: str | None = None, **kwargs):
    """按 extension + 用户偏好选 DocProcessor。

    fallback chain：
    1. 用户指定 preferred（且能处理）→ 用之
    2. extension 默认映射 → 用之
    3. 都处理不了 → raw
    """
    ext = Path(file_path).suffix.lower()

    # 1. 用户指定
    if preferred and preferred in DOC_PROCESSOR_CATALOG:
        proc_cls = DOC_PROCESSOR_CATALOG[preferred]
        proc = proc_cls(**kwargs)
        if proc.can_handle(file_path):
            return proc

    # 2. extension 默认
    default_name = _EXT_DEFAULT.get(ext)
    if default_name and default_name in DOC_PROCESSOR_CATALOG:
        proc_cls = DOC_PROCESSOR_CATALOG[default_name]
        proc = proc_cls(**kwargs)
        if proc.can_handle(file_path):
            return proc

    # 3. raw 兜底
    return RawTextProcessor(**kwargs)


def list_doc_processors() -> list[str]:
    """列出所有可用的文档处理器。"""
    return sorted(DOC_PROCESSOR_CATALOG)
