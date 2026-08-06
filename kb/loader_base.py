# -*- coding: utf-8 -*-
"""
Knowledge Base 加载器抽象基类（kb_loader_base.py）
===================================================

**职责**：所有 Loader 实现共享的公共逻辑。

**抽象**（子类必须实现）：
- `_load(source)` → 返回 list[Document] 的 raw 形式

**复用**：
- 复用 `..kb_types.Document`
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from .types import Document


def get_logger(name: str):
    from ..logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseLoader"]


class BaseLoader(ABC):
    """所有 Loader 实现继承此类。

    Loader 的职责：**只负责把 source 变成 list[Document]**。具体文本提取交给 DocProcessor。
    子类 `_load(source)` 可以选择：
    - 直接读文件 → text（RawTextLoader / FileLoader for .txt/.md）
    - 调 DocProcessor 处理（FileLoader for .pdf/.docx）
    - 调 URLLoader 拉远端（URLLoader）
    - 列出目录里所有文件 → 递归调用（DirectoryLoader）
    """
    name: str = "base"

    @abstractmethod
    def can_handle(self, source: str) -> bool:
        """是否支持此 source。"""
        ...

    @abstractmethod
    def _load(self, source: str) -> list[tuple[str, str, dict[str, Any]]]:
        """子类实现。返回 [(text, source_meta_str, meta_dict), ...]。

        - text: 文档文本
        - source_meta_str: 用于 Document.source（如文件路径、URL、raw:<id>）
        - meta_dict: Document.meta（如 page / heading / ...）
        """
        ...

    # === 公共 API ===

    def load(self, source: str) -> list[Document]:
        """加载 source → list[Document]。"""
        raws = self._load(source)
        return [
            Document(id=uuid.uuid4().hex, source=src, loader=self.name, text=text, meta=meta)
            for text, src, meta in raws
        ]

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"