# -*- coding: utf-8 -*-
"""
Phase 2 单元测试（test_kb_phase2.py）
=====================================

覆盖：kb_embedder_base / kb_reranker_base / kb_chunker_base / kb_loader_base / kb_doc_processor_base / kb_vector_store_base。

Base 类都用 stub 子类做单测，**不连真 API / 真实 Qdrant**。
"""
from __future__ import annotations

from typing import Any

import pytest

from tangyuanAI.kb_cache import NullCache
from tangyuanAI.kb_config import EmbedderConfig, RerankerConfig
from tangyuanAI.kb_embedder_base import BaseEmbedder, EmbeddingError
from tangyuanAI.kb_reranker_base import BaseReranker, RerankerError
from tangyuanAI.kb_types import Chunk, Document, KnowledgeBase
from tangyuanAI.kb_chunker_base import BaseChunker
from tangyuanAI.kb_loader_base import BaseLoader
from tangyuanAI.kb_doc_processor_base import BaseDocProcessor
from tangyuanAI.kb_vector_store_base import BaseVectorStore
from tangyuanAI.errors import APIError


# ---------------------------------------------------------------------------
# Fake Embedder（用于测 BaseEmbedder 公共逻辑）
# ---------------------------------------------------------------------------

class FakeEmbedder(BaseEmbedder):
    client_name = "fake"

    def __init__(self, config: EmbedderConfig, *, fail_n: int = 0, bad_dim: bool = False):
        self._fail_n = fail_n
        self._bad_dim = bad_dim
        super().__init__(config, cache=NullCache())

    def _init_client(self):
        return object()  # 占位

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        if self._fail_n > 0:
            self._fail_n -= 1
            raise APIError("fake transient error", status_code=503)
        if self._bad_dim:
            return [[0.0] * (self.config.embed_dim + 1) for _ in batch]
        return [[0.1] * self.config.embed_dim for _ in batch]


def _cfg(**kw) -> EmbedderConfig:
    base = dict(
        provider="openai-compatible", api_base="http://localhost:11434/v1",
        model="fake", embed_dim=4, max_retries=2,
    )
    # 过滤掉 bad_dim 这种不在 EmbedderConfig schema 里的字段
    extra = {k: kw.pop(k) for k in list(kw) if k == "bad_dim"}
    base.update(kw)
    return EmbedderConfig(**base)


# ---------------------------------------------------------------------------
# BaseEmbedder
# ---------------------------------------------------------------------------

class TestBaseEmbedder:
    @pytest.mark.asyncio
    async def test_embed_basic(self):
        e = FakeEmbedder(_cfg())
        v = await e.embed("hello")
        assert len(v) == 4

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        e = FakeEmbedder(_cfg())
        vs = await e.embed_batch(["a", "b", "c"])
        assert len(vs) == 3
        assert all(len(v) == 4 for v in vs)

    @pytest.mark.asyncio
    async def test_dim_mismatch_raises(self):
        e = FakeEmbedder(_cfg(), bad_dim=True)
        with pytest.raises(EmbeddingError):
            await e.embed("hi")

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        # fail 一次，第二次成功
        e = FakeEmbedder(_cfg(max_retries=2), fail_n=1)
        v = await e.embed("hi")
        assert len(v) == 4

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        # 一直失败
        e = FakeEmbedder(_cfg(max_retries=2), fail_n=99)
        with pytest.raises(EmbeddingError):
            await e.embed("hi")

    @pytest.mark.asyncio
    async def test_token_aware_split(self):
        e = FakeEmbedder(_cfg(embed_dim=4, batch_size=2, max_input_tokens=100))
        # 短文本应在一个 batch
        batches = e._split_by_tokens(["a", "b", "c"])
        assert sum(len(b) for b in batches) == 3

    @pytest.mark.asyncio
    async def test_cache_key_unique_per_config(self):
        e1 = FakeEmbedder(_cfg(model="m1"))
        e2 = FakeEmbedder(_cfg(model="m2"))
        assert e1._cache_key("hi") != e2._cache_key("hi")

    @pytest.mark.asyncio
    async def test_max_batch_size(self):
        e = FakeEmbedder(_cfg(batch_size=42))
        assert e.max_batch_size() == 42

    @pytest.mark.asyncio
    async def test_close(self):
        e = FakeEmbedder(_cfg())
        await e.close()


# ---------------------------------------------------------------------------
# Fake Reranker
# ---------------------------------------------------------------------------

class FakeReranker(BaseReranker):
    client_name = "fake"

    def __init__(self, config: RerankerConfig, *, fail_n: int = 0):
        self._fail_n = fail_n
        super().__init__(config, cache=NullCache())

    def _init_model(self):
        return object()

    async def _rerank_one_batch(self, query: str, chunks: list[Chunk]):
        if self._fail_n > 0:
            self._fail_n -= 1
            raise APIError("fake transient", status_code=503)
        # 简单按文本长度倒序打分（演示排序）
        return sorted(
            [(c, float(len(c.text))) for c in chunks],
            key=lambda x: x[1], reverse=True,
        )


def _rcfg(**kw) -> RerankerConfig:
    base = dict(provider="cohere", api_base="https://api.cohere.com/v2",
                model="rerank-english-v3.0", max_retries=2)
    base.update(kw)
    return RerankerConfig(**base)


class TestBaseReranker:
    @pytest.mark.asyncio
    async def test_rerank_basic(self):
        chunks = [
            Chunk(doc_id="d1", ordinal=i, text=t, token_count=1)
            for i, t in enumerate(["short", "a longer text here", "x"])
        ]
        r = FakeReranker(_rcfg())
        result = await r.rerank("query", chunks, top_k=2)
        assert len(result) == 2
        # 按 text 长度倒序
        assert result[0][0].text == "a longer text here"

    @pytest.mark.asyncio
    async def test_rerank_empty(self):
        r = FakeReranker(_rcfg())
        assert await r.rerank("q", [], top_k=5) == []
        assert await r.rerank("q", [Chunk(doc_id="d", ordinal=0, text="x", token_count=1)], top_k=0) == []

    @pytest.mark.asyncio
    async def test_rerank_retry(self):
        chunks = [Chunk(doc_id="d", ordinal=0, text="x", token_count=1)]
        r = FakeReranker(_rcfg(max_retries=2), fail_n=1)
        result = await r.rerank("q", chunks, top_k=1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rerank_retry_exhausted(self):
        chunks = [Chunk(doc_id="d", ordinal=0, text="x", token_count=1)]
        r = FakeReranker(_rcfg(max_retries=2), fail_n=99)
        with pytest.raises(RerankerError):
            await r.rerank("q", chunks, top_k=1)


# ---------------------------------------------------------------------------
# BaseChunker
# ---------------------------------------------------------------------------

class NaiveChunker(BaseChunker):
    name = "naive"

    def _split(self, text: str) -> list[str]:
        # 按字符均匀切
        if len(text) <= self.chunk_size:
            return [text]
        out, i = [], 0
        step = self.chunk_size - self.chunk_overlap
        while i < len(text):
            out.append(text[i:i + self.chunk_size])
            i += step
        return out


class TestBaseChunker:
    def test_split_basic(self):
        c = NaiveChunker(chunk_size=10, chunk_overlap=2)
        chunks = c.split("0123456789ABCDEF", meta={"src": "test"})
        assert len(chunks) >= 2
        assert all(isinstance(x, Chunk) for x in chunks)
        assert chunks[0].meta["src"] == "test"
        assert chunks[0].meta["ordinal"] == 0
        # overlap 正确
        assert chunks[0].text[-2:] == chunks[1].text[:2]

    def test_split_empty(self):
        c = NaiveChunker()
        assert c.split("") == []
        assert c.split("   ") == []

    def test_split_short(self):
        c = NaiveChunker(chunk_size=100, chunk_overlap=10)
        chunks = c.split("short text")
        assert len(chunks) == 1
        assert chunks[0].text == "short text"

    def test_overlap_must_be_lt_size(self):
        with pytest.raises(ValueError):
            NaiveChunker(chunk_size=10, chunk_overlap=10)
        with pytest.raises(ValueError):
            NaiveChunker(chunk_size=10, chunk_overlap=20)


# ---------------------------------------------------------------------------
# BaseLoader
# ---------------------------------------------------------------------------

class StringLoader(BaseLoader):
    name = "string"
    MAGIC = "kb:string:"

    def can_handle(self, source: str) -> bool:
        return source.startswith(self.MAGIC)

    def _load(self, source: str) -> list[tuple[str, str, dict]]:
        body = source[len(self.MAGIC):]
        return [(body, source, {"kind": "string"})]


class TestBaseLoader:
    def test_can_handle(self):
        assert StringLoader().can_handle("kb:string:hello")
        assert not StringLoader().can_handle("/tmp/file.txt")

    def test_load(self):
        loader = StringLoader()
        docs = loader.load("kb:string:hello world")
        assert len(docs) == 1
        assert docs[0].text == "hello world"
        assert docs[0].source == "kb:string:hello world"
        assert docs[0].loader == "string"
        assert docs[0].meta == {"kind": "string"}
        assert len(docs[0].id) == 32


# ---------------------------------------------------------------------------
# BaseDocProcessor
# ---------------------------------------------------------------------------

class TxtProcessor(BaseDocProcessor):
    name = "txt"
    supported_extensions = (".txt", ".md")

    def _process(self, file_path: str) -> list[tuple[str, dict]]:
        from pathlib import Path
        text = Path(file_path).read_text(encoding="utf-8")
        return [(text, {"file": file_path})]


class TestBaseDocProcessor:
    def test_can_handle(self):
        p = TxtProcessor()
        assert p.can_handle("/x/a.txt")
        assert p.can_handle("/x/a.md")
        assert not p.can_handle("/x/a.pdf")

    def test_process(self, tmp_path):
        p = TxtProcessor()
        f = tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        out = p.process(str(f))
        assert len(out) == 1
        assert out[0][0] == "hello"
        assert out[0][1]["file"] == str(f)


# ---------------------------------------------------------------------------
# BaseVectorStore
# ---------------------------------------------------------------------------

class _VecStoreImpl(BaseVectorStore):
    """最小实现来验证 BaseVectorStore 是 abstract。"""

    name = "fake"

    async def create_collection(self, name, dim, **kw): pass
    async def upsert(self, c, ids, vecs, payloads): pass
    async def search(self, c, qv, qt, k, **kw): return []
    async def delete(self, c, ids): pass
    async def scroll(self, c, **kw): return [], None
    async def close(self): pass


class TestBaseVectorStore:
    def test_can_instantiate_subclass(self):
        v = _VecStoreImpl()
        assert v.name == "fake"

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseVectorStore()  # type: ignore[abstract]