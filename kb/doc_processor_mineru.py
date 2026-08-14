# -*- coding: utf-8 -*-
"""
MinerU DocProcessor（kb_doc_processor_mineru.py）
==================================================

**依赖**：`magic-pdf`（optional dep `[kb-processor-mineru]`，OpenDataLab 出品）。

**强项**：学术 PDF（论文 / 书籍 / 复杂排版），布局 + 公式 + 表格识别 SOTA。
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from .doc_processor_base import BaseDocProcessor

__all__ = ["MinerUProcessor"]


class MinerUProcessor(BaseDocProcessor):
    """OpenDataLab minerU（magic-pdf）。"""
    name = "minerU"
    supported_extensions = (".pdf",)

    def __init__(
        self,
        *,
        device: str = "cuda",          # "cuda" / "cpu" / "mps"
        api_url: str | None = None,    # 云端 API（可选）
        api_key: str | None = None,    # 云端 API key
        output_dir: str | None = None, # 本地输出目录（默认 tempfile）
        model_dir: str | None = None,  # 模型目录（可选，magic-pdf 自动下载）
    ):
        self.device = device
        self.api_url = api_url
        self.api_key = api_key
        self.output_dir = output_dir
        self.model_dir = model_dir

    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        # 云端模式
        if self.api_url:
            return self._process_remote(file_path)
        # 本地模式
        return self._process_local(file_path)

    def _process_remote(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        import httpx

        resp = httpx.post(
            f"{self.api_url.rstrip('/')}/v1/extract/pdf",
            files={"file": open(file_path, "rb")},
            headers={"Authorization": f"Bearer {self.api_key or ''}"},
            timeout=300.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # 期望 {pages: [{text, meta}, ...]} 或 {content: str}
        pages = data.get("pages") or []
        if not pages and data.get("content"):
            pages = [{"text": data["content"], "meta": {}}]
        return [
            (p.get("text", ""), {**p.get("meta", {}), "file": str(file_path)})
            for p in pages if p.get("text")
        ]

    def _process_local(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        try:
            # magic-pdf 2.x 的入口
            from magic_pdf.dict2md.merger import block2md  # noqa: F401  # 触发 import
        except ImportError:
            try:
                from magic_pdf.pdf_parse_main import pdf_parse_main  # type: ignore[import-not-found]
            except ImportError as e:
                raise ImportError(
                    "magic-pdf not installed. Run `pip install tangyuanAI[kb-processor-mineru]`."
                ) from e
        else:
            # magic-pdf 3.x 的入口
            from magic_pdf.pdf_parse_main import pdf_parse_main  # type: ignore[import-not-found]

        out_dir = self.output_dir or tempfile.mkdtemp(prefix="mineru_")
        os.makedirs(out_dir, exist_ok=True)

        # pdf_parse_main(pdf_path, out_dir) → 返回 markdown 字符串 + json
        # 具体 API 随版本略有差异；这里做兼容
        try:
            result = pdf_parse_main(
                str(file_path),
                out_dir,
                device=self.device,
            )
        except TypeError:
            # 旧版签名
            result = pdf_parse_main(str(file_path), out_dir)

        if isinstance(result, str):
            md = result
        elif isinstance(result, dict):
            md = result.get("markdown") or result.get("md") or ""
        elif isinstance(result, (list, tuple)) and result:
            first = result[0]
            md = first if isinstance(first, str) else str(first)
        else:
            md = ""

        return [(md, {"file": str(file_path), "processor": "minerU"})]
