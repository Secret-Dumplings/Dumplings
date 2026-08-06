# -*- coding: utf-8 -*-
"""
Reranker provider 单元测试（test_kb_reranker_providers.py）
=========================================================

**不连真 API / 不装真模型**。用 mock。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tangyuanAI.kb_cache import NullCache
from tangyuanAI.kb_config import RerankerConfig
from tangyuanAI.kb_reranker_factory import create_reranker, list_reranker_providers
from tangyuanAI.kb_reranker_noop import NoOpReranker
from tangyuanAI.kb_types import Chunk


def _cfg(provider: str, **kw) -> RerankerConfig:
    base = dict(provider=provider, max_retries=2)
    if provider != "no-op":
        base["api_base"] = "http://localhost:11434/v1"
        base["model"] = "fake-model"
    base.update(kw)
    return RerankerConfig(**base)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_list_providers(self):
        providers = list_reranker_providers()
        for p in ["no-op", "openai-compatible", "cohere", "jina", "bge-local", "colbert", "monot5"]:
            assert p in providers

    def test_create_noop(self):
        r = create_reranker(_cfg("no-op"), cache=NullCache())
        assert isinstance(r, NoOpReranker)

    def test_unknown_provider(self):
        with pytest.raises(Exception):
            create_reranker(_cfg("nonexistent"))


# ---------------------------------------------------------------------------
# NoOp
# ---------------------------------------------------------------------------

class TestNoOp:
    @pytest.mark.asyncio
    async def test_returns_chunks_in_order(self):
        r = NoOpReranker(_cfg("no-op"), cache=NullCache())
        chunks = [Chunk(doc_id="d", ordinal=i, text=t, token_count=1) for i, t in enumerate(["a", "bb", "ccc"])]
        result = await r.rerank("query", chunks, top_k=2)
        assert len(result) == 2
        assert [c.text for c, _ in result] == ["a", "bb"]
        assert all(s == 0.0 for _, s in result)

    @pytest.mark.asyncio
    async def test_top_k_zero(self):
        r = NoOpReranker(_cfg("no-op"), cache=NullCache())
        chunks = [Chunk(doc_id="d", ordinal=0, text="x", token_count=1)]
        assert await r.rerank("q", chunks, top_k=0) == []


# ---------------------------------------------------------------------------
# OpenAI-compatible（mock）
# ---------------------------------------------------------------------------

class TestOpenAICompatibleReranker:
    @patch("tangyuanAI.kb_reranker_openai.AsyncHTTPClient")
    @pytest.mark.asyncio
    async def test_rerank_via_mock(self, MockHTTP):
        cfg = _cfg("openai-compatible", api_base="https://example.com", model="rerank-1")
        r = create_reranker(cfg, cache=NullCache())

        # Mock HTTP response
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.3},
                {"index": 1, "relevance_score": 0.9},
                {"index": 2, "relevance_score": 0.5},
            ]
        }
        r._client.apost = AsyncMock(return_value=fake_resp)

        chunks = [Chunk(doc_id="d", ordinal=i, text=t, token_count=1) for i, t in enumerate(["a", "b", "c"])]
        result = await r.rerank("query", chunks, top_k=3)
        assert len(result) == 3
        # 按 score 降序：b (0.9), c (0.5), a (0.3)
        assert result[0][0].text == "b"
        assert result[1][0].text == "c"
        assert result[2][0].text == "a"
        assert result[0][1] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# BGE / ColBERT / MonoT5（仅测试 factory 派发；不装真模型）
# ---------------------------------------------------------------------------

class TestLocalRerankers:
    def test_bge_local_in_factory(self):
        from tangyuanAI.kb_reranker_factory import _RERANKERS
        assert "bge-local" in _RERANKERS

    def test_colbert_in_factory(self):
        from tangyuanAI.kb_reranker_factory import _RERANKERS
        assert "colbert" in _RERANKERS

    def test_monot5_in_factory(self):
        from tangyuanAI.kb_reranker_factory import _RERANKERS
        assert "monot5" in _RERANKERS

    def test_bge_local_no_model(self):
        """不装 sentence-transformers 时初始化应抛错。"""
        from tangyuanAI.kb_reranker_bge import BGEReranker
        from tangyuanAI.kb_reranker_base import RerankerError
        # 确保真的没装；移除缓存的导入
        import sys
        st_modules = [m for m in sys.modules if m.startswith("sentence_transformers")]
        for m in st_modules:
            del sys.modules[m]
        cfg = _cfg("bge-local", model_path="/tmp/fake")
        try:
            import sentence_transformers  # noqa
            pytest.skip("sentence-transformers is installed, skip no-model test")
        except ImportError:
            with pytest.raises((ImportError, RerankerError)):
                BGEReranker(cfg, cache=NullCache())