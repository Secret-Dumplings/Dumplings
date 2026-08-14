# -*- coding: utf-8 -*-
"""
Directory Loader（kb_loader_directory.py）
==========================================

**职责**：递归列出目录下所有支持的文件 → 对每个文件用 FileLoader。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tangyuanAI.logging_config import get_logger

from .doc_processor_factory import _EXT_DEFAULT
from .loader_base import BaseLoader
from .loader_file import FileLoader

__all__ = ["DirectoryLoader"]

_logger = get_logger("kb.loader.directory")


class DirectoryLoader(BaseLoader):
    """目录递归加载。"""
    name = "directory"

    def __init__(
        self,
        *,
        glob: str = "**/*",
        extensions: list[str] | None = None,
        follow_symlinks: bool = False,
    ):
        self.glob = glob
        # 默认支持 DocProcessor 能处理的所有扩展名
        self.extensions = extensions or list(_EXT_DEFAULT.keys())
        self.follow_symlinks = follow_symlinks

    def can_handle(self, source: str) -> bool:
        return Path(source).is_dir()

    def _load(self, source: str) -> list[tuple[str, str, dict[str, Any]]]:
        base = Path(source).expanduser()
        if not base.is_dir():
            raise NotADirectoryError(f"not a directory: {source}")

        file_loader = FileLoader()
        out: list[tuple[str, str, dict[str, Any]]] = []
        for p in sorted(base.glob(self.glob)):
            if p.is_dir():
                continue
            if p.suffix.lower() not in self.extensions:
                continue
            try:
                # 复用 FileLoader._load（返回原始 tuple，避免二次包装）
                out.extend(file_loader._load(str(p)))
            except Exception as e:
                # 单个文件失败不中断
                _logger.warning(f"skip file {p}: {e}")
        return out
