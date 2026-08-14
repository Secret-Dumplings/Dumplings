# -*- coding: utf-8 -*-
"""
PaddleOCR DocProcessor（kb_doc_processor_paddleocr.py）
========================================================

**依赖**：`paddleocr` + `paddlepaddle`（optional dep `[kb-processor-paddleocr]`）。

**强项**：中文扫描件 / 影印件 PDF / 图片 / 复杂表格。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .doc_processor_base import BaseDocProcessor

__all__ = ["PaddleOCRProcessor"]


class PaddleOCRProcessor(BaseDocProcessor):
    """百度 PaddleOCR。"""
    name = "paddleocr"
    supported_extensions = (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif")

    def __init__(
        self,
        *,
        lang: str = "ch",
        use_gpu: bool = False,
        det_model_dir: str | None = None,
        rec_model_dir: str | None = None,
        cls_model_dir: str | None = None,
    ):
        self.lang = lang
        self.use_gpu = use_gpu
        self.det_model_dir = det_model_dir
        self.rec_model_dir = rec_model_dir
        self.cls_model_dir = cls_model_dir
        self._ocr = None  # 懒加载

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                raise ImportError(
                    "paddleocr not installed. "
                    "Run `pip install tangyuanAI[kb-processor-paddleocr]`."
                ) from e
            kwargs = dict(
                lang=self.lang,
                use_gpu=self.use_gpu,
                use_angle_cls=True,
                show_log=False,
            )
            if self.det_model_dir:
                kwargs["det_model_dir"] = self.det_model_dir
            if self.rec_model_dir:
                kwargs["rec_model_dir"] = self.rec_model_dir
            if self.cls_model_dir:
                kwargs["cls_model_dir"] = self.cls_model_dir
            self._ocr = PaddleOCR(**kwargs)
        return self._ocr

    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            pages = self._pdf_to_images(file_path)
        else:
            pages = [file_path]

        ocr = self._get_ocr()
        out: list[tuple[str, dict[str, Any]]] = []
        for i, img in enumerate(pages):
            result = ocr.ocr(img, cls=True)
            lines: list[str] = []
            # result: [[[box, (text, conf)], ...], ...]
            if result:
                for page in result:
                    if not page:
                        continue
                    for line in page:
                        if line and len(line) >= 2:
                            text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                            if text.strip():
                                lines.append(text.strip())
            out.append((
                "\n".join(lines),
                {"page": i, "file": str(file_path), "processor": "paddleocr"},
            ))
        return out

    def _pdf_to_images(self, pdf_path: str) -> list[str]:
        """PDF → 每页一张图片（用 PyMuPDF 或 pdf2image）。"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            try:
                from pdf2image import convert_from_path  # type: ignore[import-not-found]
            except ImportError as e:
                raise ImportError(
                    "PDF→image 需要 PyMuPDF（pymupdf）或 pdf2image。"
                    "Run `pip install pymupdf` 或 `pip install pdf2image`。"
                ) from e
            # fallback pdf2image
            images = convert_from_path(pdf_path)
            tmp_paths: list[str] = []
            import os
            import tempfile
            os.makedirs(tmp_paths_dir := tempfile.mkdtemp(prefix="paddleocr_pdf_"), exist_ok=True)
            for i, img in enumerate(images):
                p = os.path.join(tmp_paths_dir, f"page_{i:04d}.png")
                img.save(p)
                tmp_paths.append(p)
            return tmp_paths

        # PyMuPDF
        import os
        import tempfile
        os.makedirs(tmp_dir := tempfile.mkdtemp(prefix="paddleocr_pdf_"), exist_ok=True)
        doc = fitz.open(pdf_path)
        paths: list[str] = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            p = os.path.join(tmp_dir, f"page_{i:04d}.png")
            pix.save(p)
            paths.append(p)
        doc.close()
        return paths
