# -*- coding: utf-8 -*-
"""
Phase 4 单元测试（test_kb_phase4.py）
=====================================

覆盖：kb_registry / kb_ingest / kb_search / kb_migrate / kb_tool。

**不连真 API**：用 deterministic fake embedder（hash 向量）。
Qdrant 用 :memory: 真实例。
"""
from __future__ import annotations

import pytest

from tangyuanAI.kb.types import KnowledgeBase
from tangyuanAI.kb.config import EmbedderConfig, RerankerConfig
from tangyuanAI.kb.embedder_base import BaseEmbedder
from tangyuanAI.kb.cache import NullCache, get_global_cache, set_global_cache


# ---------------------------------------------------------------------------
# Fake embedder（deterministic hash 向量）
# ---------------------------------------------------------------------------

class FakeEmbedder(BaseEmbedder):
    client_name = "fake"

    def _init_client(self):
        return object()

    async def _embed_one_batch(self, batch):
        import hashlib
        out = []
        for text in batch:
            h = hashlib.sha256(text.encode()).digest()
            vec = [h[i] / 255.0 for i in range(min(self.dim, len(h)))]
            while len(vec) < self.dim:
                vec.append(0.0)
            out.append(vec)
        return out


def _fake_cfg(dim: int = 8, **kw) -> EmbedderConfig:
    base = dict(
        provider="openai-compatible", api_base="http://fake", model="fake",
        embed_dim=dim, max_input_tokens=1000, batch_size=10,
    )
    base.update(kw)
    return EmbedderConfig(**base)


# ---------------------------------------------------------------------------
# Fixtures：重置全局状态
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_kb_globals(monkeypatch, tmp_path):
    """每个测试清空 KB 注册表 + store cache，隔离 Qdrant，并注册 fake embedder。"""
    import tangyuanAI.kb.registry as reg
    import tangyuanAI.kb.ingest as ingest
    import tangyuanAI.kb.embedder_factory as factory
    from tangyuanAI.kb.registry import _kbs, _store_cache

    # 默认 base_dir 指向 tmp（隔离持久化）
    monkeypatch.setenv("TANGYUAN_KB_DIR", str(tmp_path))

    # 覆盖 openai-compatible → FakeEmbedder（测试隔离）
    factory._EMBEDDERS["openai-compatible"] = FakeEmbedder

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


# ---------------------------------------------------------------------------
# kb_registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_register_get(self):
        from tangyuanAI.kb.registry import register_kb, get_kb, list_kbs, delete_kb

        kb = register_kb("demo", embedder=_fake_cfg())
        assert kb.name == "demo"
        assert get_kb("demo").id == kb.id
        assert get_kb(kb.id).name == "demo"
        assert list_kbs()

    def test_duplicate_rejected(self):
        from tangyuanAI.kb.registry import register_kb
        register_kb("demo", embedder=_fake_cfg())
        with pytest.raises(ValueError, match="already exists"):
            register_kb("demo", embedder=_fake_cfg())

    def test_overwrite(self):
        from tangyuanAI.kb.registry import register_kb
        kb1 = register_kb("demo", embedder=_fake_cfg())
        kb2 = register_kb("demo", embedder=_fake_cfg(), overwrite=True)
        assert kb2.id != kb1.id

    def test_delete(self):
        from tangyuanAI.kb.registry import register_kb, delete_kb, get_kb
        register_kb("demo", embedder=_fake_cfg())
        assert delete_kb("demo")
        with pytest.raises(KeyError):
            get_kb("demo")

    def test_persistence_restore(self):
        from tangyuanAI.kb.registry import register_kb, _kbs, get_kb
        kb = register_kb("persist", embedder=_fake_cfg())
        # 模拟重启：清内存，从持久化恢复
        _kbs.clear()
        restored = get_kb("persist")
        assert restored.id == kb.id
        assert restored.embed_dim == kb.embed_dim

    def test_embed_dim_auto(self):
        from tangyuanAI.kb.registry import register_kb
        kb = register_kb("d", embedder=_fake_cfg(dim=16))
        assert kb.embed_dim == 16


# ---------------------------------------------------------------------------
# kb_ingest + kb_search（端到端，fake embedder + Qdrant :memory:）
# ---------------------------------------------------------------------------

class TestIngestSearch:
    def test_add_and_search(self):
        from tangyuanAI.kb.registry import register_kb, get_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync

        # base_dir 指向 tmp（fixture 已把 meta store 指到 tmp；但 KB.base_dir 也要 tmp）
        # fixture 的 meta_store 用的 tmp_path；KB 需要 qdrant_location 独立
        kb = register_kb(
            "kb1",
            embedder=_fake_cfg(dim=8),
            qdrant_location=":memory:",
            chunk_size=100, chunk_overlap=20
        )
        assert kb.qdrant_location == ":memory:"

        doc_ids = add_document_sync(
            "kb1",
            "raw:hello",
            raw_text="tangyuanAI 是一个多智能体协作框架。它支持向量检索。",
        )
        assert len(doc_ids) == 1

        results = search_sync("kb1", "向量检索", top_k=3)
        assert len(results) >= 1
        assert results[0].chunk.text

    def test_duplicate_dedup(self):
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync

        register_kb("k", embedder=_fake_cfg(), qdrant_location=":memory:")
        d1 = add_document_sync("k", "raw:x", raw_text="same content here")
        d2 = add_document_sync("k", "raw:y", raw_text="same content here")
        # 相同 content → 第二次跳过，返回同一 doc_id
        assert d1 == d2

    def test_no_embedder_raises(self):
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        register_kb("k", embedder=None, qdrant_location=":memory:")
        with pytest.raises(ValueError, match="no embedder"):
            add_document_sync("k", "raw:x", raw_text="hello")

    def test_list_documents(self):
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import list_documents_sync

        register_kb("k", embedder=_fake_cfg(), qdrant_location=":memory:")
        add_document_sync("k", "raw:a", raw_text="doc alpha content")
        add_document_sync("k", "raw:b", raw_text="doc beta content")
        docs = list_documents_sync("k")
        assert len(docs) == 2


# ---------------------------------------------------------------------------
# kb_migrate
# ---------------------------------------------------------------------------

class TestMigrate:
    def test_migrate_switches_model(self):
        from tangyuanAI.kb.registry import register_kb, get_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.search import search_sync
        from tangyuanAI.kb.migrate import migrate_embedding_model_sync

        kb = register_kb("m", embedder=_fake_cfg(dim=8), qdrant_location=":memory:")
        add_document_sync("m", "raw:x", raw_text="apple banana cherry document")
        assert search_sync("m", "apple", top_k=1)

        # 迁移到 dim=16 的新 fake embedder
        result = migrate_embedding_model_sync("m", _fake_cfg(dim=16))
        assert result["total_chunks"] >= 1
        assert result["new_collection"] != result["old_collection"]

        kb2 = get_kb("m")
        assert kb2.embed_dim == 16
        # 迁移后仍能搜到
        results = search_sync("m", "apple", top_k=1)
        assert len(results) >= 1

    def test_migrate_no_embedder(self):
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.migrate import migrate_embedding_model_sync
        register_kb("m2", embedder=None, qdrant_location=":memory:")
        with pytest.raises(ValueError, match="no current embedder"):
            migrate_embedding_model_sync("m2", _fake_cfg())


# ---------------------------------------------------------------------------
# kb_tool
# ---------------------------------------------------------------------------

class TestTool:
    def test_register_tools(self):
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.tool import register_kb_tools, unregister_kb_tools

        kb = register_kb("toolk", embedder=_fake_cfg(), qdrant_location=":memory:")
        add_document_sync("toolk", "raw:x", raw_text="hello tool test content")

        names = register_kb_tools(kb)
        assert "kb_toolk_search" in names
        assert "kb_toolk_list" in names
        assert "kb_toolk_add" in names

        from tangyuanAI.agent_tool import tool_registry
        assert "kb_toolk_search" in tool_registry._tools

        # 调用 proxy
        result = tool_registry._tools["kb_toolk_search"]["function"]("hello")
        assert "hello" in result

        assert unregister_kb_tools(kb)
        assert "kb_toolk_search" not in tool_registry._tools