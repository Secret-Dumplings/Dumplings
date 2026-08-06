# -*- coding: utf-8 -*-
"""
Knowledge Base 协议层（kb_protocols.py）
========================================

**职责**：所有 KB 能力的 Protocol 定义。**v7 强调**：每个能力一个 Protocol。

**为什么是 Protocol 而不是 ABC**：
- Protocol 是结构化子类型（structural subtyping），鸭子类型
- 不强制继承，第三方实现可以无侵入适配
- `runtime_checkable` 让 `isinstance(obj, Protocol)` 工作（调试用）

**复用**：
- 复用 `..errors.APIError`（运行时抛错基类）
- 复用 `..logging_config.get_logger`（debug 日志）

**分层**：
- `kb_protocols.py`（本文件）→ 只定义协议
- `kb_*_base.py` → 抽象基类（带 token-aware batch / cache / 重试公共逻辑）
- `kb_*_<provider>.py` → 具象实现
- `kb_*_factory.py` → 工厂函数
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import Chunk, Document, SearchResult


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

@runtime_checkable
class Embedder(Protocol):
    """嵌入模型协议。

    实现要点：
    - 异步批量 + token-aware 切批
    - 缓存命中走 cache（生产环境必备）
    - 失败重试（429 / 5xx）
    - 维度校验（vec 长度必须 == config.embed_dim）
    """
    name: str
    dim: int

    async def embed(self, text: str) -> list[float]:
        """单条文本 → 维度 = dim 的浮点向量。"""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入。**实现应该**走 cache + token-aware 切批 + 重试。"""
        ...

    def max_batch_size(self) -> int:
        """返回最大并发批大小。"""
        ...

    async def close(self) -> None:
        """关闭底层 client（httpx / openai SDK）。"""
        ...


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------

@runtime_checkable
class Reranker(Protocol):
    """重排模型协议。"""
    name: str

    async def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int,
    ) -> list[tuple[Chunk, float]]:
        """对 (query, chunks) 重新打分，返回 [(chunk, score), ...]，按 score 降序，长度 ≤ top_k。

        返回的 score 应当是 **relevance 分数**（越高越相关），不是概率。
        """
        ...

    async def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

@runtime_checkable
class VectorStore(Protocol):
    """向量库协议。"""
    name: str

    async def create_collection(
        self,
        name: str,
        dim: int,
        *,
        distance: str = "Cosine",
        enable_quantization: bool = True,
        **kwargs: Any,
    ) -> None:
        """创建 collection；重复创建应当幂等。"""
        ...

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        """点级原子写入（upsert）。payload 含 text / doc_id / meta 等可检索字段。"""
        ...

    async def search(
        self,
        collection: str,
        query_vec: list[float],
        query_text: str,
        top_k: int,
        *,
        filter_: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """向量检索 + 可选 payload 过滤 + 混合 BM25。

        返回 [(id, score, payload), ...]，按 score 降序。
        """
        ...

    async def delete(self, collection: str, ids: list[str]) -> None:
        """按 id 删除点。"""
        ...

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filter_: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """scroll 全部点（用于迁移 / 列表）。

        返回 (points, next_offset)；next_offset 为 None 表示没有更多。
        """
        ...

    async def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

@runtime_checkable
class Chunker(Protocol):
    """文本切分器协议（同步）。"""
    name: str

    def split(self, text: str, meta: dict[str, Any] | None = None) -> list[Chunk]:
        """把 text 切成 list[Chunk]。每个 Chunk 含 doc_id / ordinal / text / token_count / meta。"""
        ...


# ---------------------------------------------------------------------------
# DocProcessor
# ---------------------------------------------------------------------------

@runtime_checkable
class DocProcessor(Protocol):
    """文档处理服务商协议（PDF / DOCX / 图片 / 扫描件 → 结构化文本 + meta）。"""
    name: str
    supported_extensions: tuple[str, ...]

    def can_handle(self, file_path: str) -> bool:
        """是否支持此文件。"""
        ...

    def process(self, file_path: str) -> list[Document]:
        """处理文件 → list[Document]。每个 Document 含 text + meta。"""
        ...


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

@runtime_checkable
class Loader(Protocol):
    """加载器协议（如何把 source 变成 list[Document]）。"""
    name: str

    def can_handle(self, source: str) -> bool:
        """是否支持此 source。"""
        ...

    def load(self, source: str) -> list[Document]:
        """加载 source → list[Document]。"""
        ...


# ---------------------------------------------------------------------------
# EmbeddingCache（kb_cache.py 实现）
# ---------------------------------------------------------------------------

@runtime_checkable
class EmbeddingCache(Protocol):
    """嵌入缓存协议。

    性能预算：
    - 内存命中 ~1μs
    - 磁盘命中 ~100μs
    - API 调用 ~200ms
    """
    async def get(self, key: str) -> list[float] | None:
        """按 key 查缓存。无则返回 None。"""
        ...

    async def set(self, key: str, vec: list[float]) -> None:
        """写缓存。"""
        ...

    async def clear(self) -> None:
        """清缓存（CLI `kb cache clear` 用）。"""
        ...

    def stats(self) -> dict[str, Any]:
        """返回 {hits, misses, hit_rate}。"""
        ...


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

__all__ = [
    "Embedder",
    "Reranker",
    "VectorStore",
    "Chunker",
    "DocProcessor",
    "Loader",
    "EmbeddingCache",
]