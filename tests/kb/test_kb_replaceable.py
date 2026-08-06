# -*- coding: utf-8 -*-
"""
KB 替换性测试（test_kb_replaceable.py）
=======================================

**目的**：验证每个组件都能 mock / 替换，KB 整体仍能工作（保证组件解耦 + 快速技术替换）。

**替换场景**（每个单独验证）：
1. 缓存：LRUDiskCache → NullCache
2. Embedder：OpenAI-compatible → Fake
3. Reranker：NoOp → 自定义 boost
4. DocProcessor：raw → 自定义
5. Chunker：recursive → markdown
"""
from __future__ import annotations

import hashlib

import pytest

from tangyuanAI.kb.config import EmbedderConfig, RerankerConfig
from tangyuanAI.kb.embedder_base import BaseEmbedder


# ---------------------------------------------------------------------------
# 可替换组件
# ---------------------------------------------------------------------------

class FakeEmbedder(BaseEmbedder):
    client_name = "fake"

    def _init_client(self):
        return object()

    async def _embed_one_batch(self, batch):
        out = []
        for text in batch:
            h = hashlib.sha256(text.encode()).digest()
            vec = [h[i] / 255.0 for i in range(min(self.dim, len(h)))]
            while len(vec) < self.dim:
                vec.append(0.0)
            out.append(vec)
        return out


class BoostReranker:
    """自定义 reranker：给包含关键词的 chunk 加分。"""
    name = "boost"

    def __init__(self, config, *, cache=None):
        self.config = config
        self.keyword = getattr(config, "model", "") or ""

    async def rerank(self, query, chunks, top_k):
        scored = []
        for c in chunks:
            boost = 0.5 if self.keyword in c.text else 0.0
            scored.append((c, boost))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    async def close(self):
        pass


def _cfg(**kw) -> EmbedderConfig:
    base = dict(provider="openai-compatible", api_base="http://fake", model="fake",
                embed_dim=8, max_input_tokens=1000, batch_size=10)
    base.update(kw)
    return EmbedderConfig(**base)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import tangyuanAI.kb.registry as reg
    import tangyuanAI.kb.ingest as ingest
    import tangyuanAI.kb.embedder_factory as factory
    import tangyuanAI.kb.reranker_factory as rfactory
    from tangyuanAI.kb.registry import _kbs, _store_cache

    monkeypatch.setenv("TANGYUAN_KB_DIR", str(tmp_path))
    # 替换 embedder / reranker（测试替换性）
    factory._EMBEDDERS["openai-compatible"] = FakeEmbedder
    rfactory._RERANKERS["boost"] = BoostReranker

    saved = dict(_kbs)
    _kbs.clear()
    _store_cache.clear()
    ingest._store_cache.clear()
    yield
    _kbs.clear()
    _kbs.update(saved)
    _store_cache.clear()
    ingest._store_cache.clear()
    factory._EMBEDDERS["openai-compatible"] = __import__(
        "tangyuanAI.kb.embedder_openai", fromlist=["OpenAICompatibleEmbedder"]
    ).OpenAICompatibleEmbedder
    rfactory._RERANKERS.pop("boost", None)


# ---------------------------------------------------------------------------
# 替换性验证
# ---------------------------------------------------------------------------

class TestReplaceable:
    def test_replace_cache_with_null(self):
        """缓存换成 NullCache 后 KB 仍工作。"""
        from tangyuanAI.kb.cache import NullCache, set_global_cache, get_global_cache
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync

        # 换全局缓存为 NullCache
        orig = get_global_cache()
        set_global_cache(NullCache())
        try:
            register_kb("c", embedder=_cfg(), qdrant_location=":memory:")
            add_document_sync("c", "raw:x", raw_text="cache replacement test")
            assert search_sync("c", "cache", top_k=3)
        finally:
            set_global_cache(orig)

    def test_replace_embedder(self):
        """Fake embedder 替换 OpenAI-compatible 后 KB 仍工作（fixture 已替换）。"""
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync

        register_kb("e", embedder=_cfg(), qdrant_location=":memory:")
        add_document_sync("e", "raw:x", raw_text="embedder replacement content")
        assert search_sync("e", "embedder", top_k=3)

    def test_replace_reranker(self):
        """自定义 boost reranker 替换 NoOp 后 KB 仍工作，且 boost 生效。"""
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync
        import tangyuanAI.kb.reranker_factory as rfactory
        from tangyuanAI.kb.reranker_noop import NoOpReranker

        # 把 openai-compatible provider 替换为 BoostReranker（fixture 已注册 boost，这里覆盖）
        orig = rfactory._RERANKERS.get("openai-compatible")
        rfactory._RERANKERS["openai-compatible"] = BoostReranker
        try:
            register_kb(
                "r",
                embedder=_cfg(),
                reranker=RerankerConfig(
                    provider="openai-compatible",
                    model="gold",
                    api_base="http://fake",
                ),
                qdrant_location=":memory:",
            )
            add_document_sync("r", "raw:a", raw_text="this is silver document")
            add_document_sync("r", "raw:b", raw_text="this is gold document")
            results = search_sync("r", "document", top_k=2)
            assert results
            # boost reranker 应该把包含 gold 的排前面
            assert results[0].score_type.value == "rerank"
            assert "gold" in results[0].chunk.text
        finally:
            rfactory._RERANKERS["openai-compatible"] = orig

    def test_replace_chunker_to_markdown(self):
        """markdown chunker 替换 recursive。"""
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync

        register_kb("md", embedder=_cfg(), qdrant_location=":memory:",
                    chunker="markdown", chunk_size=200, chunk_overlap=20)
        add_document_sync("md", "raw:x", raw_text="# 标题\nmarkdown chunker 测试内容")
        assert search_sync("md", "markdown", top_k=3)

    def test_replace_doc_processor(self):
        """raw processor 处理 .md（fixture 默认）→ 走 RawTextProcessor。"""
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync
        from tangyuanAI.kb.doc_processor_factory import get_processor_for

        # raw 能处理 .md
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("doc processor replacement content")
            path = f.name
        proc = get_processor_for(path, preferred="raw")
        assert proc.name == "raw"

        register_kb("dp", embedder=_cfg(), qdrant_location=":memory:",
                    doc_processor="raw")
        add_document_sync("dp", path)
        assert search_sync("dp", "processor", top_k=3)