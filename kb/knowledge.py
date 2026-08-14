# -*- coding: utf-8 -*-
"""
Knowledge 类（kb/knowledge.py）
================================

**单 KB 实例**，封装 config + persistence + vector store + cache key。
- 多实例、互相隔离（独立 collection / 独立 store / 独立 cache namespace）
- 可命名、可个性化定制（subclass + 类属性 / 实例覆盖）
- AI 可直接持有实例调方法

**用法 1：subclass + 类属性**：
```python
class ResearchKB(Knowledge):
    embedder = EmbedderConfig(provider="openai", api_base="https://api.openai.com/v1",
                              model="text-embedding-3-small", embed_dim=1536)
    doc_processor = "minerU"
    chunk_size = 512

kb = ResearchKB("research_2026")
await kb.add("paper.pdf")
results = await kb.search("向量检索", top_k=5)
```

**用法 2：直接构造**（无 subclass）：
```python
kb = Knowledge("adhoc",
               embedder=EmbedderConfig(...),
               doc_processor="unstructured",
               chunk_size=256)
```

**AI 集成**：
```python
tools = kb.register_tools()  # kb_<name>_search / _list / _add
agent = Agent()
# tools 自动注入
```
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any

from tangyuanAI.logging_config import get_logger

from .config import EmbedderConfig, RerankerConfig
from .persistence import KBMetaStore
from .types import KnowledgeBase, SearchResult
from .vector_store import QdrantVectorStore

__all__ = ["Knowledge"]


_logger = get_logger("kb.knowledge")


# KnowledgeBase pydantic 字段白名单（用于从类属性 + overrides 构造 config）
_CONFIG_FIELDS = (
    "embedder", "reranker", "top_k", "doc_processor",
    "chunk_size", "chunk_overlap", "threshold", "base_dir",
    "qdrant_location", "qdrant_url", "qdrant_api_key",
    "chunker", "visibility",
)


def _safe_collection_suffix(name: str) -> str:
    """清理 KB name 作为 Qdrant collection suffix（仅 [a-zA-Z0-9_-]）。"""
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return s[:48] or "kb"


def _namespace_cache_key(kb_id: str, base_key: str) -> str:
    """给 cache key 加 namespace 隔离（多 KB 不撞）。"""
    return f"{kb_id}|{base_key}"


class Knowledge:
    """单个知识库实例。完全隔离（独立 collection / 独立 store / 独立 cache namespace）。"""

    # === 类属性（subclass 覆盖 / 实例 overrides） ===
    embedder: EmbedderConfig | None = None
    reranker: RerankerConfig | None = None
    top_k: int = 5
    doc_processor: str = "unstructured"
    chunk_size: int = 1024
    chunk_overlap: int = 200
    threshold: float = 0.0
    base_dir: str | None = None
    qdrant_location: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    chunker: str = "recursive"
    visibility: str = "private"

    def __init__(self, name: str, **overrides: Any):
        # 合并类属性 + overrides（overrides 优先）
        cfg: dict[str, Any] = {}
        for k in _CONFIG_FIELDS:
            cls_val = getattr(self.__class__, k, None)
            if cls_val is not None:
                cfg[k] = cls_val
        cfg.update(overrides)
        cfg["name"] = name
        # 验证 / 默认 base_dir
        if not cfg.get("base_dir"):
            cfg["base_dir"] = os.environ.get("TANGYUAN_KB_DIR", "./.tangyuanAI_kbs")

        # 构造 pydantic 配置模型（自动校验 + embed_dim 联动）
        self.config = KnowledgeBase(**cfg)
        # 独立 ID
        self.id = self.config.id  # pydantic 生成的 uuid
        self.name = name

        # 把 config 字段镜像为实例属性（向后兼容：kb.chunk_size / kb.base_dir / kb.embed_dim 等）。
        # 类属性仍是默认值源；实例属性 shadow 类属性，读到的就是实际 config 值。
        self._sync_mirror()

        # === 实例独立状态 ===
        # 独立 meta DB 路径（每个 KB 自己的 db 文件，避免 FK 跨 KB 冲突）
        meta_path = os.path.join(self.config.base_dir, f"{_safe_collection_suffix(name)}__{self.id[:8]}")
        self._meta = KBMetaStore(meta_path)
        # 持久化 config
        self._meta.save_kb(self.config)
        # Vector store 懒创建
        self._vs: QdrantVectorStore | None = None
        self._vs_lock = threading.RLock()
        # 资源清理
        self._closed = False

        _logger.info(
            f"Knowledge created: name={self.name} id={self.id} "
            f"embedder={self.config.embedder.provider if self.config.embedder else 'NONE'} "
            f"base_dir={self.config.base_dir}"
        )

    # === 实例属性（只读） ===

    @property
    def collection(self) -> str:
        """独立 Qdrant collection name（隔离多 KB；migrate 后指向新 collection）。"""
        if self.config.collection_name:
            return self.config.collection_name
        return f"kb__{_safe_collection_suffix(self.name)}__{self.id[:8]}"

    @property
    def kb_id(self) -> str:
        return self.id

    def _sync_mirror(self) -> None:
        """把 config 字段镜像为实例属性（config 变更后调用，如 migrate）。"""
        for _k in _CONFIG_FIELDS:
            _val = getattr(self.config, _k)
            if _k == "visibility" and hasattr(_val, "value"):
                _val = _val.value
            object.__setattr__(self, _k, _val)
        object.__setattr__(self, "embed_dim", self.config.embed_dim)

    def __getattr__(self, name: str):
        """向后兼容：把未知属性代理到 self.config（如 kb.embed_dim / kb.qdrant_location）。

        注意：__getattr__ 只在正常查找失败时调用，不会 shadow 类属性默认值。
        """
        config = object.__getattribute__(self, "config")
        if name in config.__class__.model_fields or hasattr(config, name):
            val = getattr(config, name)
            return val.value if hasattr(val, "value") and name == "visibility" else val
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    # === Vector store 懒创建（每 KB 独立客户端） ===

    @property
    def vs(self) -> QdrantVectorStore:
        if self._closed:
            raise RuntimeError(f"Knowledge {self.name!r} 已关闭")
        if self._vs is None:
            with self._vs_lock:
                if self._vs is None:
                    self._vs = QdrantVectorStore(
                        location=None if self.config.qdrant_url else (self.config.qdrant_location or f"{self.config.base_dir}/qdrant/{self.id}"),
                        url=self.config.qdrant_url,
                        api_key=self.config.qdrant_api_key,
                        enable_sparse=True,
                    )
        return self._vs

    # === Cache namespace（隔离） ===

    def _cache_namespace(self) -> str:
        return f"kb:{self.id}"

    # === 实例方法 ===

    async def add(
        self,
        source: str,
        *,
        doc_processor: str | None = None,
        raw_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[str]:
        """添加单个 source（文件路径 / URL / 内存文本）到 KB。

        Returns: doc_ids 列表。
        """
        from .ingest import _do_add
        return await _do_add(
            self, source,
            doc_processor=doc_processor, raw_text=raw_text, meta=meta,
        )

    async def add_many(
        self,
        sources: list[str],
        *,
        doc_processor: str | None = None,
        concurrency: int = 8,
    ) -> dict[str, Any]:
        """批量并发添加文档。Returns: {"success": [doc_ids], "failed": [(source, error)]}。"""
        from .ingest import add_documents as _add_documents
        return await _add_documents(
            self, sources, doc_processor=doc_processor, concurrency=concurrency,
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        use_rerank: bool | None = None,
        threshold: float | None = None,
    ) -> list[SearchResult]:
        """搜索 KB。"""
        from .search import search as _search_kb
        return await _search_kb(
            self, query,
            top_k=top_k, use_rerank=use_rerank, threshold=threshold,
        )

    async def list_documents(self) -> list[dict[str, Any]]:
        """列出 KB 的文档元数据。"""
        from .search import list_documents as _list_kb_documents
        return await _list_kb_documents(self)

    async def migrate(self, new_config: EmbedderConfig) -> dict[str, Any]:
        """切换嵌入模型（原子 swap）。"""
        from .migrate import migrate_kb
        return await migrate_kb(self, new_config)

    def register_tools(self, allowed_agents: list[str] | None = None) -> list[str]:
        """注册 KB 工具到 tool_registry。Returns: 注册的工具名列表。"""
        from .tool import register_kb_tools
        return register_kb_tools(self, allowed_agents=allowed_agents)

    def unregister_tools(self) -> bool:
        """注销 KB 工具。"""
        from .tool import unregister_kb_tools
        return unregister_kb_tools(self)

    async def shutdown(self) -> None:
        """关闭 Vector store 客户端，释放资源。"""
        with self._vs_lock:
            if self._vs is not None:
                try:
                    await self._vs.close()
                except Exception as e:
                    _logger.debug(f"close vs: {e}")
                self._vs = None
            self._closed = True
        try:
            self._meta.close()
        except Exception:
            pass

    def to_dict(self) -> dict[str, Any]:
        return self.config.model_dump()

    @classmethod
    def load(cls, name_or_id: str, base_dir: str | None = None) -> "Knowledge":
        """从持久化恢复 KB 实例。

        Args:
            name_or_id: KB 名或 id
            base_dir: KB 元数据所在目录（None → 扫默认候选）
        """
        from .registry import load_instance
        return load_instance(name_or_id, base_dir=base_dir)

    def __repr__(self) -> str:
        return f"Knowledge(name={self.name!r}, id={self.id[:8]}, collection={self.collection!r})"
