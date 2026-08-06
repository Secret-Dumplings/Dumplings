# -*- coding: utf-8 -*-
"""
KB CLI 子命令（kb_cli.py）
==========================

**职责**：`tangyuanai kb ...` 子命令。由 `cli.py` 挂载。

**命令**：
- `tangyuanai kb add <name> ...`   创建 KB + 添加文档
- `tangyuanai kb search <name> <query>`   搜索
- `tangyuanai kb list`   列出 KB
- `tangyuanai kb show <name>`   查看 KB 详情
- `tangyuanai kb delete <name>`   删除 KB
- `tangyuanai kb migrate <name> ...`   模型迁移
- `tangyuanai kb providers`   列出 provider
- `tangyuanai kb processors`   列出文档处理器
- `tangyuanai kb cache clear|stats`   缓存管理
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


__all__ = ["add_subparser", "main", "cmd_add", "cmd_search", "cmd_list", "cmd_show",
           "cmd_delete", "cmd_migrate", "cmd_providers", "cmd_processors", "cmd_cache"]


def _embedder_config_from_args(args) -> dict:
    """从 CLI 参数构造 EmbedderConfig dict。"""
    return {
        "provider": args.embedder_provider,
        "api_base": args.embedder_api_base,
        "model": args.embedder_model,
        "embed_dim": args.embedder_dim,
        "max_input_tokens": args.embedder_max_tokens,
        "api_key": args.embedder_api_key,
    }


def _reranker_config_from_args(args):
    """从 CLI 参数构造 RerankerConfig dict（None = no-op）。"""
    if not args.rerank_provider or args.rerank_provider == "no-op":
        return None
    return {
        "provider": args.rerank_provider,
        "api_base": args.rerank_api_base,
        "model": args.rerank_model,
        "api_key": args.rerank_api_key,
    }


def cmd_add(args: argparse.Namespace) -> int:
    from . import (
        EmbedderConfig, RerankerConfig, register_kb, add_document_sync,
    )

    embedder = EmbedderConfig(**_embedder_config_from_args(args)) if args.embedder_provider else None
    reranker = RerankerConfig(**_reranker_config_from_args(args)) if _reranker_config_from_args(args) else None

    kb = register_kb(
        args.name,
        embedder=embedder,
        reranker=reranker,
        top_k=args.top_k,
        doc_processor=args.doc_processor,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        threshold=args.threshold,
        qdrant_location=args.qdrant_location or "",
        qdrant_url=args.qdrant_url,
        qdrant_api_key=args.qdrant_api_key,
        base_dir=args.base_dir,
        overwrite=args.overwrite,
    )
    print(f"KB 创建成功: {kb.name} (id={kb.id})")

    if args.source or args.text or args.dir:
        sources: list[str] = []
        if args.source:
            sources.extend(args.source)
        if args.dir:
            for d in args.dir:
                sources.append(d)
        if args.text:
            doc_ids = add_document_sync(kb.name, "raw:cli", raw_text=args.text)
            print(f"  添加内存文本: {len(doc_ids)} doc")
        if sources:
            result = add_document_sync(kb.name, sources)
            print(f"  添加文档: {len(result)} chunks")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import search_sync
    results = search_sync(
        args.name, args.query,
        top_k=args.top_k, use_rerank=None if not args.no_rerank else False,
        threshold=args.threshold,
    )
    if not results:
        print("(无结果)")
        return 0
    for r in results:
        snippet = r.chunk.text[:120].replace("\n", " ")
        print(f"[{r.rank + 1}] score={r.score:.4f} ({r.score_type.value}) doc={r.chunk.doc_id[:8]}")
        print(f"    {snippet}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    from . import list_kbs
    kbs = list_kbs()
    if not kbs:
        print("(无知识库)")
        return 0
    print(f"{'名称':<24} {'嵌入模型':<36} {'文档数':<6} {'阈值':<6}")
    print("-" * 80)
    from . import list_documents_sync
    for kb in kbs:
        model = kb.embedder.model if kb.embedder else "(无)"
        try:
            n_docs = len(list_documents_sync(kb.name))
        except Exception:
            n_docs = 0
        print(f"{kb.name:<24} {model:<36} {n_docs:<6} {kb.threshold:<6}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from . import get_kb
    kb = get_kb(args.name)
    print(f"KB: {kb.name} (id={kb.id})")
    print(f"  embedder:     {kb.embedder.provider}/{kb.embedder.model} dim={kb.embed_dim}" if kb.embedder else "  embedder:     (无)")
    print(f"  reranker:     {kb.reranker.provider}/{kb.reranker.model}" if kb.reranker else "  reranker:     (no-op)")
    print(f"  doc_processor:{kb.doc_processor}")
    print(f"  chunk_size:   {kb.chunk_size}  chunk_overlap: {kb.chunk_overlap}")
    print(f"  top_k:        {kb.top_k}  threshold: {kb.threshold}")
    print(f"  qdrant:       {kb.qdrant_url or kb.qdrant_location}")
    print(f"  base_dir:     {kb.base_dir}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    from . import delete_kb
    if not args.yes:
        confirm = input(f"确认删除 KB {args.name!r}？[y/N] ")
        if confirm.lower() not in ("y", "yes"):
            print("已取消")
            return 1
    ok = delete_kb(args.name)
    print("已删除" if ok else f"未找到 KB: {args.name}")
    return 0 if ok else 1


def cmd_migrate(args: argparse.Namespace) -> int:
    from . import EmbedderConfig, migrate_embedding_model_sync
    new_config = EmbedderConfig(
        provider=args.new_embedder_provider,
        api_base=args.new_embedder_api_base,
        model=args.new_embedder_model,
        embed_dim=args.new_embedder_dim,
    )
    result = migrate_embedding_model_sync(args.name, new_config)
    print(f"迁移完成: {result['total_chunks']} chunks, {result['duration_sec']:.1f}s")
    print(f"  旧 collection: {result['old_collection']}")
    print(f"  新 collection: {result['new_collection']}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    from . import list_embedder_providers, list_reranker_providers
    kind = args.kind or "embed"
    if kind == "embed":
        print("Embedder providers:", ", ".join(list_embedder_providers()))
    else:
        print("Reranker providers:", ", ".join(list_reranker_providers()))
    return 0


def cmd_processors(_args: argparse.Namespace) -> int:
    from . import list_doc_processors
    print("Doc processors:", ", ".join(list_doc_processors()))
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    from . import get_global_cache
    cache = get_global_cache()
    if args.cache_action == "stats":
        stats = cache.stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
    elif args.cache_action == "clear":
        import asyncio
        asyncio.run(cache.clear())
        print("缓存已清空")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def add_subparser(subparsers) -> None:
    """给 cli.py 的 parser 加 `kb` subparser。"""
    p = subparsers.add_parser("kb", help="知识库管理（RAG）")
    sub = p.add_subparsers(dest="kb_action", required=True)

    # add
    p_add = sub.add_parser("add", help="创建 KB + 添加文档")
    p_add.add_argument("name")
    p_add.add_argument("--embedder-provider", choices=["openai", "openai-compatible", "cohere", "voyage", "jina"])
    p_add.add_argument("--embedder-api-base")
    p_add.add_argument("--embedder-model")
    p_add.add_argument("--embedder-api-key")
    p_add.add_argument("--embedder-dim", type=int)
    p_add.add_argument("--embedder-max-tokens", type=int, default=8191)
    p_add.add_argument("--rerank-provider", choices=["no-op", "openai-compatible", "cohere", "jina", "bge-local", "colbert", "monot5"], default="no-op")
    p_add.add_argument("--rerank-api-base")
    p_add.add_argument("--rerank-model")
    p_add.add_argument("--rerank-api-key")
    p_add.add_argument("--top-k", type=int, default=5)
    p_add.add_argument("--doc-processor", default="unstructured")
    p_add.add_argument("--chunk-size", type=int, default=1024)
    p_add.add_argument("--chunk-overlap", type=int, default=200)
    p_add.add_argument("--threshold", type=float, default=0.0)
    p_add.add_argument("--source", action="append", help="文件 / URL（可多次）")
    p_add.add_argument("--dir", action="append", help="目录（可多次）")
    p_add.add_argument("--text", help="内存文本")
    p_add.add_argument("--qdrant-location", default="")
    p_add.add_argument("--qdrant-url")
    p_add.add_argument("--qdrant-api-key")
    p_add.add_argument("--base-dir", default="./.tangyuanAI_kbs")
    p_add.add_argument("--overwrite", action="store_true")
    p_add.set_defaults(func=cmd_add)

    # search
    p_search = sub.add_parser("search", help="搜索 KB")
    p_search.add_argument("name")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int)
    p_search.add_argument("--no-rerank", action="store_true")
    p_search.add_argument("--threshold", type=float)
    p_search.set_defaults(func=cmd_search)

    # list
    p_list = sub.add_parser("list", help="列出 KB")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="查看 KB 详情")
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    # delete
    p_del = sub.add_parser("delete", help="删除 KB")
    p_del.add_argument("name")
    p_del.add_argument("--yes", action="store_true")
    p_del.set_defaults(func=cmd_delete)

    # migrate
    p_mig = sub.add_parser("migrate", help="切换嵌入模型")
    p_mig.add_argument("name")
    p_mig.add_argument("--new-embedder-provider", required=True, choices=["openai", "openai-compatible", "cohere", "voyage", "jina"])
    p_mig.add_argument("--new-embedder-api-base", required=True)
    p_mig.add_argument("--new-embedder-model", required=True)
    p_mig.add_argument("--new-embedder-dim", type=int, required=True)
    p_mig.set_defaults(func=cmd_migrate)

    # providers
    p_prov = sub.add_parser("providers", help="列出 provider")
    p_prov.add_argument("--kind", choices=["embed", "rerank"], default="embed")
    p_prov.set_defaults(func=cmd_providers)

    # processors
    p_proc = sub.add_parser("processors", help="列出文档处理器")
    p_proc.set_defaults(func=cmd_processors)

    # cache
    p_cache = sub.add_parser("cache", help="缓存管理")
    p_cache.add_argument("cache_action", choices=["stats", "clear"])
    p_cache.set_defaults(func=cmd_cache)


def main(args: argparse.Namespace) -> int:
    """kb subcommand 入口（被 cli.py main() 调用）。"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, UnicodeError):
            pass
    func = getattr(args, "func", None)
    if func is None:
        print("缺少 kb 子命令。用 `tangyuanai kb --help` 查看。")
        return 1
    return func(args)