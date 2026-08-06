# -*- coding: utf-8 -*-
"""
Knowledge Base 向量库抽象基类（kb_vector_store_base.py）
=======================================================

**职责**：所有 VectorStore 实现共享的公共逻辑。

**抽象**（子类必须实现）：
- `_create_collection` / `_upsert` / `_search` / `_delete` / `_scroll`
- 客户端管理

**复用**：
- 复用 `..kb_protocols.VectorStore`
- 复用 `..logging_config.get_logger`
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


def get_logger(name: str):
    from .logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseVectorStore"]


class BaseVectorStore(ABC):
    """所有 VectorStore 实现继承此类。

    默认实现：QdrantVectorStore（kb_vector_store.py）。
    换 Milvus / Weaviate：实现相同接口即可。
    """
    name: str = "base"

    # === 子类实现 ===

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        dim: int,
        *,
        distance: str = "Cosine",
        enable_quantization: bool = True,
        **kwargs: Any,
    ) -> None: ...

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None: ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vec: list[float],
        query_text: str,
        top_k: int,
        *,
        filter_: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]: ...

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> None: ...

    @abstractmethod
    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filter_: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    @abstractmethod
    async def close(self) -> None: ...