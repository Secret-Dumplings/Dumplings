# -*- coding: utf-8 -*-
"""
KB 性能测试（test_kb_perf.py）
==============================

**默认跳过**（`@pytest.mark.benchmark`）；用 `pytest -m benchmark` 显式跑。

**覆盖**：
1. 500 文档索引吞吐（Qdrant :memory: + fake embedder）
2. 50 并发 search latency
3. batch embed vs 单条 embed 加速比
4. 缓存命中加速比
"""
from __future__ import annotations

import asyncio
import hashlib
import time

import pytest

from tangyuanAI.kb_config import EmbedderConfig
from tangyuanAI.kb_embedder_base import BaseEmbedder


pytestmark = pytest.mark.benchmark


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


def _cfg(**kw) -> EmbedderConfig:
    base = dict(provider="openai-compatible", api_base="http://fake", model="fake",
                embed_dim=32, max_input_tokens=2000, batch_size=100)
    base.update(kw)
    return EmbedderConfig(**base)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import tangyuanAI.kb_registry as reg
    import tangyuanAI.kb_ingest as ingest
    import tangyuanAI.kb_embedder_factory as factory
    from tangyuanAI.kb_registry import _kbs, _store_cache

    monkeypatch.setenv("TANGYUAN_KB_DIR", str(tmp_path))
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
        "tangyuanAI.kb_embedder_openai", fromlist=["OpenAICompatibleEmbedder"]
    ).OpenAICompatibleEmbedder


def _make_docs(n: int, tmp_path) -> list[str]:
    """生成 n 篇 md 文档，返回路径列表。"""
    paths = []
    for i in range(n):
        p = tmp_path / f"doc{i:04d}.md"
        p.write_text(f"# 文档 {i}\n这是第 {i} 篇测试文档，主题是 topic{i % 10}。", encoding="utf-8")
        paths.append(str(p))
    return paths


class TestPerf:
    def test_500_doc_index_throughput(self, tmp_path):
        from tangyuanAI.kb_registry import register_kb
        from tangyuanAI.kb_ingest import add_documents_sync

        register_kb("perf_idx", embedder=_cfg(), qdrant_location=":memory:",
                    chunk_size=64, chunk_overlap=10)
        sources = _make_docs(500, tmp_path)

        t0 = time.perf_counter()
        result = add_documents_sync("perf_idx", sources, concurrency=8)
        dt = time.perf_counter() - t0

        assert result["failed"] == []
        assert len(result["success"]) == 500
        print(f"\n  500 docs indexed in {dt:.2f}s ({500 / dt:.0f} docs/s)")
        assert dt < 60.0  # 宽松上限（CI 慢机器）

    def test_50_concurrent_search_latency(self, tmp_path):
        from tangyuanAI.kb_registry import register_kb
        from tangyuanAI.kb_ingest import add_documents_sync

        register_kb("perf_search", embedder=_cfg(), qdrant_location=":memory:",
                    chunk_size=100, chunk_overlap=20)
        add_documents_sync("perf_search", _make_docs(200, tmp_path), concurrency=8)

        async def _one():
            return await _search_async("perf_search", "topic5", top_k=5)

        t0 = time.perf_counter()
        results = asyncio.run(_run_concurrent(50))
        dt = time.perf_counter() - t0

        assert len(results) == 50
        print(f"\n  50 concurrent searches in {dt:.2f}s (avg {dt / 50 * 1000:.1f}ms/query)")
        assert dt < 10.0  # 宽松

    def test_batch_vs_single_embed(self):
        import asyncio
        from tangyuanAI.kb_embedder_factory import create_embedder
        from tangyuanAI.kb_cache import NullCache

        e = create_embedder(_cfg(), cache=NullCache())
        texts = [f"text {i} with some words to embed" for i in range(100)]

        # 单条
        t0 = time.perf_counter()
        for t in texts:
            asyncio.run(e.embed(t))
        single_dt = time.perf_counter() - t0

        # batch
        t0 = time.perf_counter()
        asyncio.run(e.embed_batch(texts))
        batch_dt = time.perf_counter() - t0

        print(f"\n  single={single_dt:.3f}s batch={batch_dt:.3f}s speedup={single_dt / max(batch_dt, 1e-6):.1f}x")
        assert batch_dt < single_dt  # batch 至少比单条快

    def test_cache_hit_speedup(self):
        import asyncio
        from tangyuanAI.kb_embedder_factory import create_embedder
        from tangyuanAI.kb_cache import get_global_cache

        e = create_embedder(_cfg(), cache=get_global_cache())
        text = "cache benchmark text"

        # 冷
        t0 = time.perf_counter()
        asyncio.run(e.embed(text))
        cold_dt = time.perf_counter() - t0

        # 热
        t0 = time.perf_counter()
        asyncio.run(e.embed(text))
        hot_dt = time.perf_counter() - t0

        print(f"\n  cold={cold_dt:.4f}s hot={hot_dt:.6f}s speedup={cold_dt / max(hot_dt, 1e-6):.1f}x")
        assert hot_dt <= cold_dt


async def _search_async(name, query, top_k):
    from tangyuanAI.kb_search import search
    return await search(name, query, top_k=top_k)


async def _run_concurrent(n):
    return await asyncio.gather(*[_search_async("perf_search", "topic5", top_k=5) for _ in range(n)])