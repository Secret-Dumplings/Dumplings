# -*- coding: utf-8 -*-
"""
Embedder provider 单元测试（test_kb_embedder_providers.py）
=========================================================

覆盖：factory dispatch + 各 provider 单测（用 mock）。
**不连真 API**。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tangyuanAI.kb.cache import NullCache
from tangyuanAI.kb.config import EmbedderConfig
from tangyuanAI.kb.embedder_factory import create_embedder, list_embedder_providers
from tangyuanAI.kb.embedder_jina import JinaEmbedder
from tangyuanAI.kb.embedder_openai import OpenAICompatibleEmbedder


def _cfg(provider: str, **kw) -> EmbedderConfig:
    base = dict(
        provider=provider,
        api_base="http://localhost:11434/v1",
        model="fake-model",
        embed_dim=4,
    )
    base.update(kw)
    return EmbedderConfig(**base)


@pytest.fixture(autouse=True)
def _restore_real_embedders():
    """本文件测真实 provider（不是 FakeEmbedder），恢复 factory 映射。"""
    import tangyuanAI.kb.embedder_factory as factory
    from tangyuanAI.kb.embedder_openai import OpenAICompatibleEmbedder
    factory._EMBEDDERS["openai-compatible"] = OpenAICompatibleEmbedder
    factory._EMBEDDERS["openai"] = OpenAICompatibleEmbedder
    yield


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_list_providers(self):
        providers = list_embedder_providers()
        assert "openai" in providers
        assert "openai-compatible" in providers
        assert "jina" in providers
        assert "voyage" in providers
        assert "cohere" in providers

    def test_unknown_provider(self):
        # pydantic Literal 校验先拦一道
        with pytest.raises(Exception):
            create_embedder(_cfg("nonexistent"))

    @patch.object(OpenAICompatibleEmbedder, "_init_client", return_value=MagicMock())
    def test_create_openai(self, _):
        e = create_embedder(_cfg("openai"), cache=NullCache())
        assert isinstance(e, OpenAICompatibleEmbedder)

    @patch.object(OpenAICompatibleEmbedder, "_init_client", return_value=MagicMock())
    def test_create_openai_compatible(self, _):
        e = create_embedder(_cfg("openai-compatible"), cache=NullCache())
        assert isinstance(e, OpenAICompatibleEmbedder)


# ---------------------------------------------------------------------------
# OpenAI-compatible（mock _embed_one_batch）
# ---------------------------------------------------------------------------

class TestOpenAICompatible:
    @patch.object(OpenAICompatibleEmbedder, "_init_client", return_value=MagicMock())
    @pytest.mark.asyncio
    async def test_embed_via_mock(self, _):
        cfg = _cfg("openai", api_base="https://api.openai.com/v1", embed_dim=4)
        e = create_embedder(cfg, cache=NullCache())

        fake_vecs = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
        e._embed_one_batch = AsyncMock(return_value=fake_vecs)

        out = await e.embed_batch(["a", "b"])
        assert out == fake_vecs

    @patch.object(OpenAICompatibleEmbedder, "_init_client", return_value=MagicMock())
    @pytest.mark.asyncio
    async def test_dim_mismatch_propagates(self, _):
        cfg = _cfg("openai", embed_dim=4)
        e = create_embedder(cfg, cache=NullCache())
        e._embed_one_batch = AsyncMock(return_value=[[0.0] * 3])

        with pytest.raises(Exception):
            await e.embed("x")


# ---------------------------------------------------------------------------
# Jina（mock AsyncHTTPClient）
# ---------------------------------------------------------------------------

class TestJina:
    @patch.object(JinaEmbedder, "_init_client", return_value=MagicMock())
    @pytest.mark.asyncio
    async def test_embed_via_mock(self, _):
        cfg = _cfg("jina", api_base="https://api.jina.ai", model="jina-embeddings-v3", embed_dim=4)
        e = JinaEmbedder(cfg, cache=NullCache())

        fake_response = MagicMock()
        fake_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3, 0.4]},
                {"embedding": [0.5, 0.6, 0.7, 0.8]},
            ]
        }
        e._client.apost = AsyncMock(return_value=fake_response)

        out = await e._embed_one_batch(["a", "b"])
        assert out == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]

    @patch.object(JinaEmbedder, "_init_client", return_value=MagicMock())
    def test_supported_provider_in_factory(self, _):
        e = create_embedder(_cfg("jina"), cache=NullCache())
        assert isinstance(e, JinaEmbedder)


# ---------------------------------------------------------------------------
# Cohere（仅测试 factory 派发；cohere SDK 未装，_init_client 会抛 ImportError）
# ---------------------------------------------------------------------------

class TestCohereFactory:
    def test_cohere_provider(self):
        from tangyuanAI.kb.embedder_cohere import CohereEmbedder
        cfg = _cfg("cohere", api_base="https://api.cohere.com", embed_dim=4)
        with patch.object(CohereEmbedder, "_init_client", side_effect=ImportError("cohere not installed")):
            with pytest.raises(Exception):
                create_embedder(cfg, cache=NullCache())
        # 重新派发验证 provider 在 _EMBEDDERS 中
        from tangyuanAI.kb.embedder_factory import _EMBEDDERS
        assert "cohere" in _EMBEDDERS


# ---------------------------------------------------------------------------
# Voyage（仅测试 factory 派发）
# ---------------------------------------------------------------------------

class TestVoyageFactory:
    @patch("tangyuanAI.kb.embedder_voyage.AsyncHTTPClient")
    def test_voyage_provider(self, _):
        from tangyuanAI.kb.embedder_voyage import VoyageEmbedder
        cfg = _cfg("voyage", api_base="https://api.voyageai.com", embed_dim=4)
        e = create_embedder(cfg, cache=NullCache())
        assert isinstance(e, VoyageEmbedder)
