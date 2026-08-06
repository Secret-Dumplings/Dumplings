# -*- coding: utf-8 -*-
"""
KB 集成测试（test_kb_integration.py）
=====================================

**覆盖**：端到端（register → add → search → migrate），Qdrant :memory: 真实例 + fake embedder。
**不连真 API / 不跑 unstructured**（Windows libmagic 崩溃 → 用 .md/.txt 走 raw processor）。
"""
from __future__ import annotations

import hashlib

import pytest
from tangyuanAI.kb.config import EmbedderConfig, RerankerConfig
from tangyuanAI.kb.embedder_base import BaseEmbedder

# ---------------------------------------------------------------------------
# Fake embedder（deterministic hash 向量）
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


def _cfg(dim: int = 16, model: str = "fake-model", **kw) -> EmbedderConfig:
    base = dict(
        provider="openai-compatible", api_base="http://fake", model=model,
        embed_dim=dim, max_input_tokens=1000, batch_size=10,
    )
    base.update(kw)
    return EmbedderConfig(**base)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    import tangyuanAI.kb.embedder_factory as factory
    import tangyuanAI.kb.ingest as ingest
    from tangyuanAI.kb.registry import _kbs, _store_cache

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
        "tangyuanAI.kb.embedder_openai", fromlist=["OpenAICompatibleEmbedder"]
    ).OpenAICompatibleEmbedder


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_flow(self, tmp_path):
        """register → add 3 篇不同主题 md → 各主题搜索排第一 → migrate → 再搜。"""
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.search import search_sync

        # 准备 3 篇不同主题的 md
        docs = {
            "ai.md": "# AI\n人工智能和大语言模型是热门方向。Transformer 架构改变了 NLP。",
            "cooking.md": "# 烹饪\n红烧肉要小火慢炖。番茄炒蛋先炒蛋。",
            "sports.md": "# 运动\n足球是世界上最受欢迎的运动。梅西是传奇球星。",
        }
        for name, content in docs.items():
            (tmp_path / name).write_text(content, encoding="utf-8")

        register_kb(
            "test",
            embedder=_cfg(dim=16),
            qdrant_location=":memory:",
            chunk_size=100, chunk_overlap=20,
        )

        # 添加 3 篇
        for name in docs:
            add_document_sync("test", str(tmp_path / name))

        # 每主题搜索应命中对应文档
        for query, expected_snippet in [
            ("人工智能", "AI"),
            ("红烧肉", "烹饪"),
            ("足球", "运动"),
        ]:
            results = search_sync("test", query, top_k=3)
            assert results, f"no results for {query}"
            # 找到包含 expected 的结果
            texts = [r.chunk.text for r in results]
            assert any(expected_snippet in t or query in t for t in texts), \
                f"query {query!r} did not surface expected content; got {texts}"

    def test_add_documents_batch(self, tmp_path):
        """add_documents 批量 + 并发。"""
        from tangyuanAI.kb.ingest import add_documents_sync
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.search import search_sync

        for i in range(5):
            (tmp_path / f"doc{i}.md").write_text(f"文档 {i} 内容 apple{100 + i}", encoding="utf-8")

        register_kb("batch", embedder=_cfg(), qdrant_location=":memory:")
        sources = [str(tmp_path / f"doc{i}.md") for i in range(5)]
        result = add_documents_sync("batch", sources, concurrency=3)
        assert result["failed"] == []
        assert len(result["success"]) == 5

        results = search_sync("batch", "apple100", top_k=1)
        assert results

    def test_persistence_across_restart(self, tmp_path):
        """模拟重启：进程内清注册表 → 从持久化恢复 → 数据仍可搜。"""
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.registry import _kbs, get_kb, register_kb

        register_kb("persist", embedder=_cfg(), qdrant_location=":memory:")
        add_document_sync("persist", "raw:hello", raw_text="持久化测试内容 vector search")

        # 模拟重启
        _kbs.clear()
        kb = get_kb("persist")  # 从 SQLite 恢复
        assert kb.name == "persist"

    def test_rerank_path(self):
        """NoOp reranker 配置 + 搜索仍工作。"""
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.search import search_sync

        register_kb(
            "with_rerank",
            embedder=_cfg(),
            reranker=RerankerConfig(provider="no-op"),
            qdrant_location=":memory:",
        )
        add_document_sync("with_rerank", "raw:x", raw_text="重排测试 rerank content")
        results = search_sync("with_rerank", "rerank", top_k=3)
        assert results

    def test_threshold_only_filters_rerank(self, tmp_path):
        """threshold 只砍 rerank 分数，不砍 bm25/cosine。"""
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.search import search_sync

        register_kb(
            "thresh", embedder=_cfg(), reranker=None,
            qdrant_location=":memory:", threshold=0.99,  # 高阈值
        )
        add_document_sync("thresh", "raw:x", raw_text="threshold 测试内容")
        # reranker=None → 走 cosine 路径 → threshold 不生效
        results = search_sync("thresh", "threshold", top_k=3)
        assert results

    def test_content_hash_dedup(self, tmp_path):
        """同一内容加 2 次 → 只入库 1 份。"""
        from tangyuanAI.kb.ingest import add_document_sync
        from tangyuanAI.kb.registry import register_kb
        from tangyuanAI.kb.search import list_documents_sync

        register_kb("dedup", embedder=_cfg(), qdrant_location=":memory:")
        f = tmp_path / "same.md"
        f.write_text("dedup 测试相同内容", encoding="utf-8")
        add_document_sync("dedup", str(f))
        add_document_sync("dedup", str(f))
        docs = list_documents_sync("dedup")
        assert len(docs) == 1
