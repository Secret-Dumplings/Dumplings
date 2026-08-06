# -*- coding: utf-8 -*-
"""
KB 工具桥接（kb_tool.py）
=========================

**职责**：把 KB 暴露成 tool_registry 工具，让 Agent 通过 Function Calling 调用。

**复用**：完全仿 `skill_bridge.py` 的模式。

**注册 3 个工具**：
- `kb_<name>_search(query, top_k=5)` → markdown 摘要
- `kb_<name>_list()` → 文档列表
- `kb_<name>_add(source, doc_processor=None)` → 添加文档
"""
from __future__ import annotations

import json

from ..agent_tool import tool_registry
from ..logging_config import get_logger

__all__ = ["register_kb_tools", "unregister_kb_tools"]

_logger = get_logger("kb.tool")


def _format_search_results(results) -> str:
    """把 SearchResult 列表格式化成 markdown 给 LLM。"""
    lines = [f"## 搜索结果（{len(results)} 条）"]
    for r in results:
        snippet = r.chunk.text[:300].replace("\n", " ")
        lines.append(
            f"\n**[{r.rank + 1}]** score={r.score:.3f} ({r.score_type.value}) | "
            f"doc={r.chunk.doc_id[:8]} | {snippet}"
        )
    return "\n".join(lines)


def register_kb_tools(kb, *, allowed_agents=None) -> list[str]:
    """把 KB 注册为 3 个工具。返回注册的工具名列表。"""
    from .ingest import add_document_sync
    from .search import list_documents_sync, search_sync

    kb_name = kb.name
    names: list[str] = []

    def _search(query: str, top_k: int = 5) -> str:
        """搜索知识库，返回相关片段（markdown）。"""
        try:
            results = search_sync(kb_name, query, top_k=top_k)
            return _format_search_results(results)
        except Exception as e:
            _logger.error(f"kb_search {kb_name}: {e}")
            return f"搜索失败: {e}"

    def _list() -> str:
        """列出知识库中的所有文档。"""
        try:
            docs = list_documents_sync(kb_name)
            if not docs:
                return "知识库为空"
            lines = [f"## {kb_name} 文档（{len(docs)} 个）"]
            for d in docs:
                lines.append(f"- `{d['source']}` (chunks={d['chunk_count']})")
            return "\n".join(lines)
        except Exception as e:
            _logger.error(f"kb_list {kb_name}: {e}")
            return f"列出文档失败: {e}"

    def _add(source: str, doc_processor: str | None = None) -> str:
        """往知识库添加文档（文件路径 / URL / 目录）。"""
        try:
            doc_ids = add_document_sync(kb_name, source, doc_processor=doc_processor)
            return json.dumps({"added": doc_ids, "count": len(doc_ids)}, ensure_ascii=False)
        except Exception as e:
            _logger.error(f"kb_add {kb_name}: {e}")
            return f"添加文档失败: {e}"

    for func, desc, params in [
        (
            _search,
            f"搜索知识库 {kb_name!r}。返回相关文档片段及其分数。",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "top_k": {"type": "integer", "description": "返回条数", "default": 5},
                },
                "required": ["query"],
            },
        ),
        (
            _list,
            f"列出知识库 {kb_name!r} 中的所有文档。",
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        (
            _add,
            f"往知识库 {kb_name!r} 添加文档（文件 / URL / 目录）。",
            {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "文件路径 / URL / 目录"},
                    "doc_processor": {"type": "string", "description": "可选：unstructured / minerU / paddleocr / raw"},
                },
                "required": ["source"],
            },
        ),
    ]:
        name = f"kb_{kb_name}_{func.__name__.lstrip('_')}"
        try:
            decorator = tool_registry.register_tool(
                allowed_agents=allowed_agents,
                description=desc,
                name=name,
                parameters=params,
            )
            decorator(func)
            names.append(name)
            _logger.info(f"KB tool registered: {name}")
        except Exception as e:
            _logger.error(f"register KB tool {name} failed: {e}")

    return names


def unregister_kb_tools(kb) -> bool:
    """从 tool_registry 移除 KB 的工具。"""
    kb_name = kb.name
    names = [f"kb_{kb_name}_{suffix}" for suffix in ("search", "list", "add")]
    removed = False
    for name in names:
        if name in tool_registry._tools:
            del tool_registry._tools[name]
            removed = True
            _logger.info(f"KB tool removed: {name}")
    return removed
