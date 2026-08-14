# -*- coding: utf-8 -*-
"""
Knowledge Base 文档处理器抽象基类（kb_doc_processor_base.py）
============================================================

**职责**：所有 DocProcessor 实现共享的公共逻辑。

**抽象**（子类必须实现）：
- `_process(file_path)` → 返回 list[(text, meta), ...]

**支持的扩展名**：子类在类属性 `supported_extensions` 里声明。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


def get_logger(name: str):
    from tangyuanAI.logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseDocProcessor"]


class BaseDocProcessor(ABC):
    """所有 DocProcessor 实现继承此类。

    DocProcessor 的职责：把文件（PDF / DOCX / 图片 / 扫描件）变成结构化文本 + meta。
    """
    name: str = "base"
    supported_extensions: tuple[str, ...] = ()

    def can_handle(self, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    @abstractmethod
    def _process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        """子类实现。返回 [(text, meta), ...]。

        - text: 文档文本（每页 / 每段一个 tuple）
        - meta: 文本对应的元数据（page / heading / table / figure 等）
        """
        ...

    def process(self, file_path: str) -> list[tuple[str, dict[str, Any]]]:
        """公共入口。子类 _process 拿到的是 page 级列表。"""
        return self._process(file_path)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, ext={self.supported_extensions})"
