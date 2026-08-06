# -*- coding: utf-8 -*-
"""
Knowledge Base 数据模型（kb_types.py）
=====================================

**职责**：所有 KB 相关的 pydantic 模型 / dataclass / Enum，**只放数据形状**，不放逻辑。

**复用**：
- 复用 `..errors.APIError` 作为异常基类
- 复用 `..logging_config.get_logger` 作为日志入口
- **不复用** `..persistence.*`（KB 持久化是独立领域，自己有 `kb_persistence.py`）

**层级**：所有 `Chunk` / `Document` / `SearchResult` / `KnowledgeBase` 都是 pydantic v2 BaseModel，
可序列化（`model_dump_json()` / `model_validate()`），跨进程传递没问题。
"""
from __future__ import annotations

import datetime as _dt
import enum
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScoreKind(str, enum.Enum):
    """搜索结果分数类型。"""
    BM25 = "bm25"
    COSINE = "cosine"
    RRF = "rrf"             # Reciprocal Rank Fusion（混合召回）
    RERANK = "rerank"       # 重排模型打分


class Visibility(str, enum.Enum):
    """知识库可见性。
    - private：只对创建者 / ACL 命中 agent 可见
    - public：对所有 agent 可见
    """
    PRIVATE = "private"
    PUBLIC = "public"


# ---------------------------------------------------------------------------
# EmbeddingCache protocol 占位（在 kb_cache.py 里实现；这里只是类型提示）
# 真实的 EmbeddingCache 是 Protocol，runtime_checkable，下面的 type alias 只是 hint
# ---------------------------------------------------------------------------

class _CacheProtocolPlaceholder:  # pragma: no cover
    pass


EmbeddingCache = Any  # type: ignore[misc,assignment]  # 真实类型见 kb_cache.py


# ---------------------------------------------------------------------------
# Chunk（向量库里的最小检索单元）
# ---------------------------------------------------------------------------

class Chunk(BaseModel):
    """文档切片：包含文本 + 元数据 + 可选 embedding。"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: str = Field(..., description="所属文档 id")
    ordinal: int = Field(..., ge=0, description="在所属文档中的序号（从 0 开始）")
    text: str = Field(..., min_length=1, description="chunk 文本")
    token_count: int = Field(..., ge=0, description="token 数（用 tiktoken cl100k_base 计）")
    meta: dict[str, Any] = Field(default_factory=dict, description="附加元数据（page / heading / ...）")

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Chunk.id cannot be empty")
        return v


# ---------------------------------------------------------------------------
# Document（从 DocProcessor 出来的结构化文档）
# ---------------------------------------------------------------------------

class Document(BaseModel):
    """DocProcessor 输出的文档：text + meta。"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source: str = Field(..., description="原始来源（path / url / raw:...）")
    loader: str = Field(..., description="使用的 loader 名字（file / url / dir / raw）")
    doc_processor: str | None = Field(None, description="使用的 doc processor 名字")
    text: str = Field(..., min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict, description="page / heading / figure / table / ...")


# ---------------------------------------------------------------------------
# SearchResult（搜索命中）
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    """单条搜索结果。"""
    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    score: float = Field(..., description="统一分数（score_type 决定语义）")
    score_type: ScoreKind = Field(..., description="分数类型")
    bm25: Optional[float] = Field(None, description="原始 BM25 分数（如适用）")
    cosine: Optional[float] = Field(None, description="原始余弦相似度（如适用）")
    rerank: Optional[float] = Field(None, description="重排模型分数（如适用）")
    rank: int = Field(..., ge=0, description="在结果中的排名（0 = 最相关）")

    def to_dict(self) -> dict[str, Any]:
        """便于序列化给 LLM 用。"""
        return {
            "rank": self.rank,
            "score": self.score,
            "score_type": self.score_type.value,
            "text": self.chunk.text,
            "doc_id": self.chunk.doc_id,
            "chunk_id": self.chunk.id,
            "meta": self.chunk.meta,
        }


# ---------------------------------------------------------------------------
# DocMeta（持久化层用的文档元数据）
# ---------------------------------------------------------------------------

class DocMeta(BaseModel):
    """文档元数据：存在 SQLite 里，做 dedup / list 用。"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="文档 id（UUID hex）")
    kb_id: str = Field(..., description="所属 KB id")
    source: str = Field(..., description="原始来源")
    loader: str = Field(..., description="loader 名字")
    doc_processor: str | None = Field(None)
    content_hash: str = Field(..., description="md5(全文本)；用于 dedup")
    chunk_count: int = Field(..., ge=0)
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# KnowledgeBase（核心配置模型，用户钦定字段）
# ---------------------------------------------------------------------------

class KnowledgeBase(BaseModel):
    """知识库配置。

    **用户钦定字段**（按 README/CLI/接口暴露的）：
    - name
    - embedder: EmbedderConfig | None
    - reranker: RerankerConfig | None
    - top_k: int（请求文档片段数）
    - doc_processor: 文档处理服务商（unstructured / minerU / openminerU / paddleocr / raw）
    - chunk_size: int（分段大小）
    - chunk_overlap: int（重叠大小）
    - threshold: float（匹配度阈值；只对 rerank 分数生效）

    **内部字段**（用户不应直接设）：
    - id / base_dir / qdrant_* / chunker / visibility / created_at / updated_at
    """
    model_config = ConfigDict(extra="forbid")

    # === 用户钦定字段 ===
    name: str = Field(..., min_length=1, max_length=128)
    embedder: Optional[Any] = Field(None, description="EmbedderConfig；None = 不嵌入")
    reranker: Optional[Any] = Field(None, description="RerankerConfig；None = no-op")
    top_k: int = Field(5, ge=1, le=100, description="请求文档片段数")
    doc_processor: Literal["unstructured", "minerU", "openminerU", "paddleocr", "raw"] = "unstructured"
    chunk_size: int = Field(1024, ge=64, le=100_000, description="分段大小（字符）")
    chunk_overlap: int = Field(200, ge=0, le=10_000, description="重叠大小（字符）")
    threshold: float = Field(0.0, ge=0.0, le=1.0, description="匹配度阈值（仅 rerank 分数生效）")

    # === 内部实现字段 ===
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    embed_dim: int = Field(0, ge=0, description="从 embedder.embed_dim 自动填")
    base_dir: str = "./.tangyuanAI_kbs"
    qdrant_location: str = ""             # embedded Qdrant 路径（留空时默认 ./base_dir/qdrant）
    qdrant_url: Optional[str] = None      # server Qdrant URL（与 qdrant_location 二选一）
    qdrant_api_key: Optional[str] = None
    chunker: Literal["recursive", "markdown", "token", "html"] = "recursive"
    visibility: Visibility = Visibility.PRIVATE
    created_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())

    @model_validator(mode="after")
    def _check_overlap(self) -> "KnowledgeBase":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be < chunk_size ({self.chunk_size})"
            )
        return self

    @model_validator(mode="after")
    def _check_embedder_dim(self) -> "KnowledgeBase":
        """embedder 给定则必须 embed_dim > 0 且与 embedder.embed_dim 一致。"""
        if self.embedder is not None:
            # 延迟 import 避免循环
            try:
                ed = int(getattr(self.embedder, "embed_dim", 0))
            except Exception:
                ed = 0
            if ed <= 0:
                raise ValueError("embedder.embed_dim must be > 0")
            if self.embed_dim == 0:
                # 自动同步
                object.__setattr__(self, "embed_dim", ed)
            elif self.embed_dim != ed:
                raise ValueError(
                    f"KB.embed_dim ({self.embed_dim}) != embedder.embed_dim ({ed}); "
                    "either omit KB.embed_dim (auto-filled) or set it equal to embedder.embed_dim"
                )
        return self

    @model_validator(mode="after")
    def _check_qdrant(self) -> "KnowledgeBase":
        """qdrant_location 与 qdrant_url 至少有一个非空。"""
        if not self.qdrant_location and not self.qdrant_url:
            # 默认 embedded 到 base_dir/qdrant
            object.__setattr__(
                self, "qdrant_location",
                f"{self.base_dir.rstrip('/')}/qdrant/{self.id}",
            )
        return self


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

__all__ = [
    "ScoreKind",
    "Visibility",
    "Chunk",
    "Document",
    "SearchResult",
    "DocMeta",
    "KnowledgeBase",
    "EmbeddingCache",  # type alias；真实 Protocol 在 kb_cache.py
]