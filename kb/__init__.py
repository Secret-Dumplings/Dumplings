# -*- coding: utf-8 -*-
"""
Knowledge Base 主入口（kb 包）
==============================

**职责**：re-export 全部 KB 顶层 API + 数据模型。**只聚合，不含实现**（实现在各子模块）。

**使用**：
```python
import tangyuanAI as t
from tangyuanAI.kb import EmbedderConfig

t.register_kb("demo", embedder=EmbedderConfig(
    provider="openai", api_base="https://api.openai.com/v1",
    model="text-embedding-3-small", embed_dim=1536))
t.add_document_sync("demo", source="README.md")
results = t.search_sync("demo", "怎么用", top_k=3)
```
"""
from __future__ import annotations

# === 缓存（kb_cache.py） ===
from .cache import (
    LRUDiskCache,
    NullCache,
    get_global_cache,
    set_global_cache,
)
from .chunker_factory import create_chunker, list_chunkers

# === 配置（kb_config.py） ===
from .config import EmbedderConfig, RerankerConfig
from .doc_processor_factory import get_processor_for, list_doc_processors

# === 工厂 / 目录 ===
from .embedder_factory import create_embedder, list_embedder_providers
from .ingest import (
    add_document,
    add_document_sync,
    add_documents,
    add_documents_sync,
    shutdown_kb,
)

# === 核心类（kb_knowledge.py）===
from .knowledge import Knowledge
from .loader_factory import create_loader, list_loaders
from .migrate import migrate_embedding_model, migrate_embedding_model_sync

# === 协议（kb_protocols.py） ===
from .protocols import (
    Chunker,
    DocProcessor,
    Embedder,
    EmbeddingCache,
    Loader,
    Reranker,
    VectorStore,
)

# === 编排层 ===
from .registry import delete_kb, get_kb, list_kbs, register_kb
from .reranker_factory import create_reranker, list_reranker_providers
from .search import (
    list_documents,
    list_documents_sync,
    search,
    search_sync,
)
from .tool import register_kb_tools, unregister_kb_tools

# === 数据模型（kb_types.py） ===
from .types import (
    Chunk,
    DocMeta,
    Document,
    KnowledgeBase,
    ScoreKind,
    SearchResult,
    Visibility,
)

__all__ = [
    # 数据模型
    "KnowledgeBase", "Chunk", "Document", "DocMeta", "SearchResult",
    "ScoreKind", "Visibility",
    # 配置
    "EmbedderConfig", "RerankerConfig",
    # 协议
    "Embedder", "Reranker", "VectorStore", "Chunker", "DocProcessor",
    "Loader", "EmbeddingCache",
    # 缓存
    "LRUDiskCache", "NullCache", "get_global_cache", "set_global_cache",
    # KB CRUD
    "register_kb", "get_kb", "list_kbs", "delete_kb",
    # 核心类
    "Knowledge",
    # 文档
    "add_document", "add_document_sync", "add_documents", "add_documents_sync",
    # 资源清理
    "shutdown_kb",
    # 检索
    "search", "search_sync", "list_documents", "list_documents_sync",
    # 迁移
    "migrate_embedding_model", "migrate_embedding_model_sync",
    # 工具桥接
    "register_kb_tools", "unregister_kb_tools",
    # 工厂 / 目录
    "create_embedder", "create_reranker", "create_chunker", "create_loader",
    "get_processor_for",
    "list_embedder_providers", "list_reranker_providers",
    "list_chunkers", "list_loaders", "list_doc_processors",
]
