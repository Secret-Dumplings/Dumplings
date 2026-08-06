# -*- coding: utf-8 -*-
"""
Loader 工厂（kb_loader_factory.py）
===================================

**职责**：按 source 类型（文件 / URL / 目录 / raw）分派到具体 Loader。
"""
from __future__ import annotations

from pathlib import Path

from .loader_file import FileLoader
from .loader_url import URLLoader
from .loader_directory import DirectoryLoader
from .loader_raw import RawTextLoader


__all__ = ["create_loader", "list_loaders"]


def create_loader(source: str, *, raw_text: str | None = None, **kwargs):
    """按 source 类型创建 loader。

    - raw_text 给定时 → RawTextLoader
    - source 以 http(s):// 开头 → URLLoader
    - source 是目录 → DirectoryLoader
    - 否则 → FileLoader
    """
    if raw_text is not None:
        return RawTextLoader(raw_text, source=source)

    if source.startswith(("http://", "https://")):
        return URLLoader(**{k: v for k, v in kwargs.items() if k in ("timeout", "max_size")})

    if Path(source).expanduser().is_dir():
        dir_kwargs = {k: kwargs[k] for k in ("glob", "extensions", "follow_symlinks") if k in kwargs}
        return DirectoryLoader(**dir_kwargs)

    return FileLoader()


def list_loaders() -> list[str]:
    return ["file", "url", "directory", "raw"]