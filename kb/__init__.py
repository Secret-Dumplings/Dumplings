# -*- coding: utf-8 -*-
"""tangyuanai.kb —— Knowledge Base 子系统。

**两种使用模式**：

1. **默认（vendored）**：``pip install tangyuanai`` 自带完整 KB 实现，开箱即用。
   本包对外 API 全部从同级 vendored 子模块直接 import。

2. **第三方替换**：安装替代 KB 包（通过 ``tangyuanai plugin install <git-url>`` 或
   ``pip install`` 任意含 ``tangyuanai.plugins`` entry point 的包）后，本包会
   自动优先使用第三方实现，vendored 代码作为 fallback。
"""
from __future__ import annotations

from ..plugin_api import PLUGIN_TYPE_KNOWLEDGE_BASE
from ..plugin_loader import install_module_alias, resolve_plugin_for_namespace

# ---------------------------------------------------------------------------
# 1) 第三方插件（如有）→ 通过 install_module_alias 接管 tangyuanAI.kb 命名空间
# ---------------------------------------------------------------------------

_third_party = resolve_plugin_for_namespace(PLUGIN_TYPE_KNOWLEDGE_BASE)
if _third_party is not None:
    install_module_alias(__name__, _third_party)
    _SELF = _third_party
else:
    _SELF = None


# ---------------------------------------------------------------------------
# 2) Fallback：本地 vendored 实现（直接 import 同级子模块）
# ---------------------------------------------------------------------------

if _SELF is None:
    # 缓存（cache.py）
    from .cache import (  # noqa: E402
        LRUDiskCache,
        NullCache,
        get_global_cache,
        set_global_cache,
    )

    # 切分器
    from .chunker_factory import create_chunker, list_chunkers  # noqa: E402

    # 配置
    from .config import EmbedderConfig, RerankerConfig  # noqa: E402

    # 文档处理器
    from .doc_processor_factory import (  # noqa: E402
        get_processor_for,
        list_doc_processors,
    )

    # Embedder 工厂
    from .embedder_factory import (  # noqa: E402
        create_embedder,
        list_embedder_providers,
    )

    # 文档写入 / 资源清理
    from .ingest import (  # noqa: E402
        add_document,
        add_document_sync,
        add_documents,
        add_documents_sync,
        shutdown_kb,
    )

    # 核心类
    from .knowledge import Knowledge  # noqa: E402

    # Loader 工厂
    from .loader_factory import create_loader, list_loaders  # noqa: E402

    # 模型迁移
    from .migrate import (  # noqa: E402
        migrate_embedding_model,
        migrate_embedding_model_sync,
    )

    # 协议
    from .protocols import (  # noqa: E402
        Chunker,
        DocProcessor,
        Embedder,
        EmbeddingCache,
        Loader,
        Reranker,
        VectorStore,
    )

    # KB CRUD
    from .registry import (  # noqa: E402
        delete_kb,
        get_kb,
        list_kbs,
        register_kb,
    )

    # Reranker 工厂
    from .reranker_factory import (  # noqa: E402
        create_reranker,
        list_reranker_providers,
    )

    # 检索
    from .search import (  # noqa: E402
        list_documents,
        list_documents_sync,
        search,
        search_sync,
    )

    # 工具桥接
    from .tool import register_kb_tools, unregister_kb_tools  # noqa: E402

    # 数据模型
    from .types import (  # noqa: E402
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
