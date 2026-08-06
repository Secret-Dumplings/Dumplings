# -*- coding: utf-8 -*-
"""
Open MinerU DocProcessor（kb_doc_processor_openmineru.py）
==========================================================

**依赖**：`openmineru`（optional dep `[kb-processor-openminerU]`，开源版 minerU）。
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from .doc_processor_base import BaseDocProcessor

__all__ = ["OpenMinerUProcessor"]


class OpenMinerUProcessor(BaseDocProcessor):
    """开源版 minerU（openmineru）。"""
    name = "openminerU"
    supported_extensions = (".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg")

    def __init__(self, *, device: str = "cuda", output_dir: str | None = None):
        self.device = device
        self.output_dir = output_dir

    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        try:
            from openmineru import parse  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "openmineru not installed. Run `pip install tangyuanAI[kb-processor-openminerU]`."
            ) from e

        out_dir = self.output_dir or tempfile.mkdtemp(prefix="openmineru_")
        os.makedirs(out_dir, exist_ok=True)

        result = parse(str(file_path), device=self.device)

        if isinstance(result, str):
            md = result
        elif isinstance(result, dict):
            md = result.get("markdown") or result.get("md") or result.get("text") or ""
        else:
            md = str(result)

        return [(md, {"file": str(file_path), "processor": "openminerU"})]
