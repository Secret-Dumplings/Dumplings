# -*- coding: utf-8 -*-
"""
Phase 1 单元测试（test_kb_phase1.py）
=====================================

覆盖：kb_types / kb_config / kb_protocols / kb_persistence / kb_cache。
"""
from __future__ import annotations

import os
import tempfile
import time

import pytest

from tangyuanAI.kb.types import (
    Chunk,
    Document,
    DocMeta,
    KnowledgeBase,
    ScoreKind,
    SearchResult,
    Visibility,
)
from tangyuanAI.kb.config import EmbedderConfig, RerankerConfig
from tangyuanAI.kb.protocols import (
    Chunker,
    DocProcessor,
    Embedder,
    EmbeddingCache,
    Loader,
    Reranker,
    VectorStore,
)
from tangyuanAI.kb.persistence import KBMetaStore
from tangyuanAI.kb.cache import (
    LRUDiskCache,
    NullCache,
    get_global_cache,
    make_cache_key,
    set_global_cache,
)


# ---------------------------------------------------------------------------
# kb_types
# ---------------------------------------------------------------------------

class TestChunk:
    def test_basic(self):
        c = Chunk(id="c1", doc_id="d1", ordinal=0, text="hello", token_count=1)
        assert c.id == "c1"
        assert c.doc_id == "d1"
        assert c.ordinal == 0
        assert c.token_count == 1
        assert c.meta == {}

    def test_default_id(self):
        c = Chunk(doc_id="d1", ordinal=0, text="hi", token_count=1)
        assert len(c.id) == 32  # uuid4 hex

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            Chunk(doc_id="d1", ordinal=0, text="x", token_count=1, foo="bar")

    def test_empty_text(self):
        with pytest.raises(Exception):
            Chunk(doc_id="d1", ordinal=0, text="", token_count=0)

    def test_empty_id_rejected(self):
        with pytest.raises(Exception):
            Chunk(id="  ", doc_id="d1", ordinal=0, text="x", token_count=1)


class TestKnowledgeBase:
    def test_minimal(self):
        kb = KnowledgeBase(name="test")
        assert kb.name == "test"
        assert kb.top_k == 5
        assert kb.doc_processor == "unstructured"
        assert kb.chunk_size == 1024
        assert kb.chunk_overlap == 200
        assert kb.threshold == 0.0
        assert kb.visibility == Visibility.PRIVATE

    def test_overlap_lt_size(self):
        with pytest.raises(Exception):
            KnowledgeBase(name="t", chunk_size=100, chunk_overlap=100)

    def test_overlap_gt_size_rejected(self):
        with pytest.raises(Exception):
            KnowledgeBase(name="t", chunk_size=100, chunk_overlap=200)

    def test_embedder_dim_required(self):
        cfg = EmbedderConfig(
            provider="openai", api_base="https://api.openai.com/v1",
            model="text-embedding-3-small", embed_dim=1536,
        )
        kb = KnowledgeBase(name="t", embedder=cfg)
        assert kb.embed_dim == 1536  # auto-filled

    def test_embedder_dim_mismatch(self):
        cfg = EmbedderConfig(
            provider="openai", api_base="https://api.openai.com/v1",
            model="x", embed_dim=1536,
        )
        with pytest.raises(Exception):
            KnowledgeBase(name="t", embedder=cfg, embed_dim=768)

    def test_threshold_range(self):
        with pytest.raises(Exception):
            KnowledgeBase(name="t", threshold=1.5)
        with pytest.raises(Exception):
            KnowledgeBase(name="t", threshold=-0.1)

    def test_qdrant_default_path(self):
        kb = KnowledgeBase(name="t", base_dir="/tmp/foo")
        assert kb.qdrant_location.endswith(kb.id)
        assert "/tmp/foo/" in kb.qdrant_location

    def test_json_roundtrip(self):
        kb = KnowledgeBase(name="t")
        j = kb.model_dump_json()
        kb2 = KnowledgeBase.model_validate_json(j)
        assert kb.name == kb2.name
        assert kb.id == kb2.id


class TestSearchResult:
    def test_score_kinds(self):
        c = Chunk(doc_id="d1", ordinal=0, text="x", token_count=1)
        for kind in [ScoreKind.BM25, ScoreKind.COSINE, ScoreKind.RRF, ScoreKind.RERANK]:
            r = SearchResult(chunk=c, score=0.5, score_type=kind, rank=0)
            assert r.score_type == kind


# ---------------------------------------------------------------------------
# kb_config
# ---------------------------------------------------------------------------

class TestEmbedderConfig:
    def test_minimal(self):
        cfg = EmbedderConfig(
            provider="openai", api_base="https://api.openai.com/v1",
            model="text-embedding-3-small", embed_dim=1536,
        )
        assert cfg.api_key is None
        assert cfg.max_input_tokens == 8191
        assert cfg.batch_size == 100
        assert cfg.timeout == 60.0

    def test_api_base_normalized(self):
        cfg = EmbedderConfig(
            provider="openai", api_base="https://api.openai.com/v1/",
            model="x", embed_dim=1536,
        )
        assert cfg.api_base == "https://api.openai.com/v1"

    def test_api_base_scheme(self):
        with pytest.raises(Exception):
            EmbedderConfig(provider="openai", api_base="not-a-url", model="x", embed_dim=1)

    def test_resolve_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("TANGYUAN_OPENAI_API_KEY", "sk-test")
        cfg = EmbedderConfig(
            provider="openai", api_base="https://api.openai.com/v1",
            model="x", embed_dim=1,
        )
        assert cfg.resolve_api_key() == "sk-test"

    def test_resolve_api_key_empty_for_local(self):
        cfg = EmbedderConfig(
            provider="openai-compatible", api_base="http://localhost:11434/v1",
            model="x", embed_dim=1,
        )
        assert cfg.resolve_api_key() == "EMPTY"

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            EmbedderConfig(
                provider="openai", api_base="https://api.openai.com/v1",
                model="x", embed_dim=1, foo="bar",
            )


class TestRerankerConfig:
    def test_no_op(self):
        cfg = RerankerConfig(provider="no-op")
        assert cfg.provider == "no-op"

    def test_remote_requires_api_base(self):
        with pytest.raises(Exception):
            RerankerConfig(provider="cohere", model="rerank-english-v3.0")

    def test_remote_requires_model(self):
        with pytest.raises(Exception):
            RerankerConfig(provider="cohere", api_base="https://api.cohere.com/v2")

    def test_local_requires_model_or_path(self):
        with pytest.raises(Exception):
            RerankerConfig(provider="bge-local")

    def test_local_with_path(self):
        cfg = RerankerConfig(provider="bge-local", model_path="/tmp/model")
        assert cfg.resolve_model_path() == "/tmp/model"

    def test_local_with_hf_name(self):
        cfg = RerankerConfig(provider="bge-local", model="BAAI/bge-reranker-large")
        assert cfg.resolve_model_path() == "BAAI/bge-reranker-large"


# ---------------------------------------------------------------------------
# kb_protocols（runtime_checkable 检查）
# ---------------------------------------------------------------------------

class TestProtocols:
    def test_protocols_runtime_checkable(self):
        class _E:
            name = "x"
            dim = 3

            async def embed(self, t): return [0.0, 0.0, 0.0]
            async def embed_batch(self, ts): return [[0.0, 0.0, 0.0] for _ in ts]
            def max_batch_size(self): return 10
            async def close(self): pass

        assert isinstance(_E(), Embedder)

    def test_make_cache_key_stable(self):
        k1 = make_cache_key("openai", "https://api.openai.com/v1", "text-embedding-3-small", "hi")
        k2 = make_cache_key("openai", "https://api.openai.com/v1", "text-embedding-3-small", "hi")
        k3 = make_cache_key("openai", "https://api.openai.com/v1", "text-embedding-3-small", "HI")
        assert k1 == k2
        assert k1 != k3
        assert len(k1) == 64


# ---------------------------------------------------------------------------
# kb_persistence
# ---------------------------------------------------------------------------

class TestKBMetaStore:
    @pytest.fixture
    def store(self, tmp_path):
        s = KBMetaStore(str(tmp_path))
        yield s
        s.close()

    def _make_kb(self, name: str = "test", **kw) -> KnowledgeBase:
        return KnowledgeBase(name=name, **kw)

    def test_save_and_load(self, store):
        kb = self._make_kb()
        store.save_kb(kb)
        loaded = store.load_kb(kb.name)
        assert loaded is not None
        assert loaded.id == kb.id
        assert loaded.name == kb.name

    def test_load_by_id(self, store):
        kb = self._make_kb(name="by_id")
        store.save_kb(kb)
        loaded = store.load_kb(kb.id)
        assert loaded is not None
        assert loaded.name == "by_id"

    def test_list_kbs(self, store):
        store.save_kb(self._make_kb(name="a"))
        store.save_kb(self._make_kb(name="b"))
        store.save_kb(self._make_kb(name="c"))
        names = [kb.name for kb in store.list_kbs()]
        assert names == ["a", "b", "c"]

    def test_delete_kb(self, store):
        kb = self._make_kb(name="del")
        store.save_kb(kb)
        assert store.delete_kb(kb.name)
        assert store.load_kb(kb.name) is None

    def test_doc_dedup(self, store):
        kb = self._make_kb(name="k1")
        store.save_kb(kb)
        meta = DocMeta(
            id="d1", kb_id=kb.id, source="x.txt", loader="file",
            content_hash="abc", chunk_count=5,
        )
        store.add_doc(meta)
        assert store.has_doc_with_hash(kb.id, "abc")
        assert not store.has_doc_with_hash(kb.id, "zzz")

        found = store.find_doc_by_hash(kb.id, "abc")
        assert found is not None
        assert found.id == "d1"

    def test_doc_delete_cascade(self, store):
        kb = self._make_kb(name="cascade")
        store.save_kb(kb)
        store.add_doc(DocMeta(id="d1", kb_id=kb.id, source="x", loader="file",
                              content_hash="h1", chunk_count=1))
        store.add_doc(DocMeta(id="d2", kb_id=kb.id, source="y", loader="file",
                              content_hash="h2", chunk_count=1))
        assert store.count_docs(kb.id) == 2
        store.delete_kb(kb.name)
        assert store.count_docs(kb.id) == 0

    def test_list_docs(self, store):
        kb = self._make_kb(name="l")
        store.save_kb(kb)
        for i in range(3):
            store.add_doc(DocMeta(
                id=f"d{i}", kb_id=kb.id, source=f"s{i}", loader="file",
                content_hash=f"h{i}", chunk_count=i + 1,
            ))
        docs = store.list_docs(kb.id)
        assert len(docs) == 3
        assert [d.source for d in docs] == ["s0", "s1", "s2"]


# ---------------------------------------------------------------------------
# kb_cache
# ---------------------------------------------------------------------------

class TestLRUDiskCache:
    @pytest.fixture
    def cache(self, tmp_path):
        c = LRUDiskCache(memory_size=100, db_path=tmp_path / "cache.db")
        yield c
        c.close()

    @pytest.mark.asyncio
    async def test_set_get(self, cache):
        await cache.set("k1", [0.1, 0.2, 0.3])
        v = await cache.get("k1")
        assert v == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_miss(self, cache):
        assert await cache.get("missing") is None
        stats = cache.stats()
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_hit(self, cache):
        await cache.set("k1", [1.0, 2.0])
        await cache.get("k1")
        await cache.get("k1")
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path):
        c1 = LRUDiskCache(memory_size=10, db_path=tmp_path / "cache.db")
        await c1.set("k1", [1.0, 2.0, 3.0])
        c1.close()

        c2 = LRUDiskCache(memory_size=10, db_path=tmp_path / "cache.db")
        v = await c2.get("k1")
        assert v == [1.0, 2.0, 3.0]
        c2.close()

    @pytest.mark.asyncio
    async def test_memory_lru_eviction(self, cache):
        for i in range(150):
            await cache.set(f"k{i}", [float(i)])
        stats = cache.stats()
        assert stats["memory_entries"] <= 100

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        await cache.set("k1", [1.0])
        await cache.clear()
        assert await cache.get("k1") is None


class TestNullCache:
    @pytest.mark.asyncio
    async def test_never_hits(self):
        c = NullCache()
        await c.set("k", [1.0, 2.0])
        assert await c.get("k") is None
        assert c.stats()["misses"] == 1


class TestGlobalCache:
    def test_swap(self):
        original = get_global_cache()
        assert original is not None
        try:
            null = NullCache()
            set_global_cache(null)
            assert get_global_cache() is null
        finally:
            set_global_cache(original)