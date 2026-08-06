# -*- coding: utf-8 -*-
"""
Unstructured DocProcessor（kb_doc_processor_unstructured.py）
============================================================

**依赖**：`unstructured`（required dep）。

**支持格式**：PDF / DOCX / DOC / HTML / MD / EPUB / XLSX / CSV / JSON / PPTX / 图片（含 OCR，可选）。
"""
from __future__ import annotations

from typing import Any

from .doc_processor_base import BaseDocProcessor

__all__ = ["UnstructuredProcessor"]


class UnstructuredProcessor(BaseDocProcessor):
    """unstructured.partition 通用处理器。"""
    name = "unstructured"
    supported_extensions = (
        ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".txt",
        ".epub", ".xlsx", ".xls", ".csv", ".json", ".pptx", ".rtf",
    )

    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        try:
            from unstructured.partition.auto import partition
        except ImportError as e:
            raise ImportError(
                "unstructured not installed. Run `pip install tangyuanAI` (it's a required dep)."
            ) from e

        elements = partition(filename=str(file_path))
        # 合并文本元素；元素类型写进 meta
        out: list[tuple[str, dict[str, Any]]] = []
        current_parts: list[str] = []
        current_meta: dict[str, Any] = {"file": str(file_path)}
        last_type = None

        for el in elements:
            text = getattr(el, "text", "") or ""
            if not text.strip():
                continue
            el_type = type(el).__name__  # e.g. Title / NarrativeText / Table / ListItem
            if last_type is not None and el_type != last_type:
                # 类型切换：收一段
                if current_parts:
                    out.append(("".join(current_parts), dict(current_meta)))
                    current_parts = []
            current_parts.append(text)
            last_type = el_type

            # 记录类型出现
            current_meta.setdefault("element_types", set()).add(el_type)

        if current_parts:
            out.append(("".join(current_parts), dict(current_meta)))

        if not out:
            out.append(("", {"file": str(file_path)}))

        # element_types set 不能直接存（不可 JSON）；转 list
        for _, meta in out:
            if "element_types" in meta and isinstance(meta["element_types"], set):
                meta["element_types"] = sorted(meta["element_types"])
        return out
