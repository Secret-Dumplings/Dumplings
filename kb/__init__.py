# -*- coding: utf-8 -*-
"""tangyuanai.kb —— Knowledge Base 命名空间桥（实现由 RAG 插件提供）。

- 安装了 RAG 插件（``tangyuanai-rag-plus``，entry point ``rag``，type=knowledge_base）时：
  本包整体别名到插件 API。``from tangyuanAI.kb.config import EmbedderConfig`` 等价于
  ``from tangyuanAI_rag_plus.config import EmbedderConfig``（含深层子模块）。
- 未安装时：``import tangyuanAI.kb`` 本身可导入，但取任何 API 会得到清晰的安装提示。

安装：
    pip install "tangyuanAI[all]"            # 安装全部插件
    pip install tangyuanai-rag-plus          # 只装 RAG 插件

接口文档：docs/plugin-dev.md
"""
from __future__ import annotations

from ..plugin_api import PLUGIN_TYPE_KNOWLEDGE_BASE
from ..plugin_loader import install_module_alias, resolve_plugin_for_namespace

_impl = resolve_plugin_for_namespace(PLUGIN_TYPE_KNOWLEDGE_BASE)
if _impl is not None:
    install_module_alias(__name__, _impl)
    _SELF = _impl
else:
    _SELF = None


def __getattr__(name):
    if _SELF is None:
        raise ImportError(
            "RAG 插件未安装，无法访问 tangyuanAI.kb API。"
            "安装方式：pip install 'tangyuanAI[all]' 或 pip install tangyuanai-rag-plus"
        )
    return getattr(_SELF, name)


def __dir__():
    if _SELF is not None:
        return sorted(set(globals()) | set(dir(_SELF)))
    return sorted(globals())


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
