# -*- coding: utf-8 -*-
"""
Phase 3 其余 provider 单测（test_kb_phase3.py）
===============================================

覆盖：kb_chunker_* / kb_loader_* / kb_doc_processor_* / kb_vector_store / kb_sparse。

**不装真模型**：unstructured / magic-pdf / paddleocr 用 mock；Qdrant 用 :memory: 真实例。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tangyuanAI.kb.chunker_recursive import RecursiveCharChunker
from tangyuanAI.kb.chunker_markdown import MarkdownChunker
from tangyuanAI.kb.chunker_token import TokenChunker
from tangyuanAI.kb.chunker_html import HTMLChunker
from tangyuanAI.kb.chunker_factory import create_chunker, list_chunkers

from tangyuanAI.kb.loader_file import FileLoader
from tangyuanAI.kb.loader_raw import RawTextLoader
from tangyuanAI.kb.loader_directory import DirectoryLoader
from tangyuanAI.kb.loader_url import URLLoader
from tangyuanAI.kb.loader_factory import create_loader

from tangyuanAI.kb.doc_processor_raw import RawTextProcessor
from tangyuanAI.kb.doc_processor_unstructured import UnstructuredProcessor
from tangyuanAI.kb.doc_processor_factory import get_processor_for, list_doc_processors

from tangyuanAI.kb.sparse import Bm25SparseVectorizer, SparseVector
from tangyuanAI.kb.vector_store import QdrantVectorStore


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

class TestRecursiveCharChunker:
    def test_splits_long_text(self):
        c = RecursiveCharChunker(chunk_size=50, chunk_overlap=10)
        text = "This is a test. " * 30  # 450 chars
        chunks = c.split(text)
        assert len(chunks) > 1
        assert all(chunk.token_count > 0 for chunk in chunks)
        # overlap 存在
        assert chunks[0].text[-10:] in chunks[1].text

    def test_short_text_single_chunk(self):
        c = RecursiveCharChunker()
        chunks = c.split("hello world")
        assert len(chunks) == 1


class TestMarkdownChunker:
    def test_header_split(self):
        c = MarkdownChunker(chunk_size=1000, chunk_overlap=50)
        text = "# Title\n\nintro text here\n\n## Section A\n\naaa\n\n## Section B\n\nbbb"
        chunks = c.split(text)
        assert len(chunks) >= 1


class TestTokenChunker:
    def test_token_based(self):
        c = TokenChunker(chunk_size=20, chunk_overlap=5)
        text = "word " * 200
        chunks = c.split(text)
        assert len(chunks) > 1


class TestHTMLChunker:
    def test_html_split(self):
        c = HTMLChunker(chunk_size=500, chunk_overlap=50)
        html = "<html><body><h1>Title</h1><p>hello</p><h2>Sub</h2><p>world</p></body></html>"
        chunks = c.split(html)
        assert len(chunks) >= 1


class TestChunkerFactory:
    def test_list_chunkers(self):
        names = list_chunkers()
        assert "recursive" in names
        assert "markdown" in names
        assert "token" in names
        assert "html" in names

    def test_create_recursive(self):
        c = create_chunker("recursive")
        assert isinstance(c, RecursiveCharChunker)

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown chunker"):
            create_chunker("nonexistent")


# ---------------------------------------------------------------------------
# DocProcessor
# ---------------------------------------------------------------------------

class TestRawTextProcessor:
    def test_read_file(self, tmp_path):
        p = RawTextProcessor()
        f = tmp_path / "note.txt"
        f.write_text("hello kb", encoding="utf-8")
        assert p.can_handle(str(f))
        out = p.process(str(f))
        assert out[0][0] == "hello kb"


class TestUnstructuredProcessor:
    def test_can_handle(self):
        p = UnstructuredProcessor()
        assert p.can_handle("/x/a.pdf")
        assert p.can_handle("/x/b.docx")
        assert p.can_handle("/x/c.html")

    def test_process_mock(self, tmp_path):
        """mock sys.modules 里的 unstructured，避免 Windows libmagic 崩溃。"""
        import sys
        from types import ModuleType

        # 构造 fake unstructured.partition.auto.partition
        class _El:
            def __init__(self, text, el_type="NarrativeText"):
                self.text = text
                self.__class__.__name__ = el_type

        fake_partition = MagicMock(return_value=[_El("Title text"), _El("Body paragraph")])

        fake_auto = ModuleType("unstructured.partition.auto")
        fake_auto.partition = fake_partition
        fake_partition_mod = ModuleType("unstructured.partition")
        fake_partition_mod.auto = fake_auto

        fake_unstructured = ModuleType("unstructured")
        fake_unstructured.partition = fake_partition_mod

        # 注入 sys.modules（保留原有模块引用以便恢复）
        saved = {}
        for name in ("unstructured", "unstructured.partition", "unstructured.partition.auto"):
            saved[name] = sys.modules.get(name)
            sys.modules[name] = {  # type: ignore[assignment]
                "unstructured": fake_unstructured,
                "unstructured.partition": fake_partition_mod,
                "unstructured.partition.auto": fake_auto,
            }[name]

        try:
            p = UnstructuredProcessor()
            f = tmp_path / "a.pdf"
            f.write_bytes(b"%PDF-1.4 fake")
            out = p.process(str(f))
            assert len(out) == 1
            assert "Title text" in out[0][0]
        finally:
            # 恢复
            for name, mod in saved.items():
                if mod is not None:
                    sys.modules[name] = mod
                else:
                    sys.modules.pop(name, None)


class TestProcessorFactory:
    def test_dispatch_by_ext(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("# hi", encoding="utf-8")
        proc = get_processor_for(str(f))
        assert proc.name == "raw"  # .md → raw

    def test_dispatch_pdf(self, tmp_path):
        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF")
        proc = get_processor_for(str(f))
        assert proc.name == "unstructured"  # .pdf → unstructured

    def test_dispatch_image(self, tmp_path):
        f = tmp_path / "a.png"
        f.write_bytes(b"fake png")
        proc = get_processor_for(str(f))
        assert proc.name == "paddleocr"

    def test_preferred_override(self, tmp_path):
        # raw 能处理 .txt；preferred 强制用 raw（即使默认也是 raw）
        f = tmp_path / "a.txt"
        f.write_text("hello", encoding="utf-8")
        proc = get_processor_for(str(f), preferred="raw")
        assert proc.name == "raw"

    def test_list(self):
        names = list_doc_processors()
        for n in ["unstructured", "minerU", "openminerU", "paddleocr", "raw"]:
            assert n in names


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class TestFileLoader:
    def test_load_txt(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("# hello kb", encoding="utf-8")
        loader = FileLoader()
        assert loader.can_handle(str(f))
        docs = loader.load(str(f))
        assert len(docs) == 1
        assert docs[0].loader == "file"

    def test_not_found(self):
        loader = FileLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/nonexistent/file.txt")


class TestRawTextLoader:
    def test_load(self):
        loader = RawTextLoader("hello world", source="raw:test")
        docs = loader.load("anything")
        assert docs[0].text == "hello world"
        assert docs[0].loader == "raw"


class TestDirectoryLoader:
    def test_load_dir(self, tmp_path):
        (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
        (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.md").write_text("gamma", encoding="utf-8")
        loader = DirectoryLoader()
        assert loader.can_handle(str(tmp_path))
        docs = loader.load(str(tmp_path))
        assert len(docs) == 3


class TestURLLoader:
    def test_can_handle(self):
        assert URLLoader().can_handle("https://example.com")
        assert not URLLoader().can_handle("/local/file.txt")

    @patch("tangyuanAI.http_utils.HTTPClient")
    def test_load_mock(self, MockHTTP):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.headers = {"content-type": "text/plain"}
        fake_resp.content = b"hello from url"
        fake_resp.text = "hello from url"
        MockHTTP.return_value.get.return_value = fake_resp

        loader = URLLoader()
        docs = loader.load("https://example.com/hello.txt")
        assert docs[0].text == "hello from url"

    @patch("tangyuanAI.http_utils.HTTPClient")
    def test_load_html_clean(self, MockHTTP):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.headers = {"content-type": "text/html"}
        fake_resp.content = b"<html><body><script>bad()</script><p>good text</p></body></html>"
        fake_resp.text = "<html><body><script>bad()</script><p>good text</p></body></html>"
        MockHTTP.return_value.get.return_value = fake_resp

        loader = URLLoader()
        docs = loader.load("https://example.com/page")
        assert "good text" in docs[0].text
        assert "bad()" not in docs[0].text


class TestLoaderFactory:
    def test_file(self):
        assert isinstance(create_loader("/tmp/x.txt"), FileLoader)

    def test_url(self):
        assert isinstance(create_loader("https://example.com"), URLLoader)

    def test_raw(self):
        assert isinstance(create_loader("anything", raw_text="hi"), RawTextLoader)


# ---------------------------------------------------------------------------
# Sparse vectorizer
# ---------------------------------------------------------------------------

class TestBm25Sparse:
    def test_fit_and_encode(self):
        sv = Bm25SparseVectorizer()
        sv.fit(["apple banana", "apple cherry", "grape wine"])
        assert sv.vocab_size() >= 4
        v = sv.encode("apple")
        assert v.indices
        assert v.values

    def test_encode_sorted_indices(self):
        sv = Bm25SparseVectorizer()
        sv.fit(["apple banana cherry", "grape"])
        v = sv.encode("cherry banana apple")
        assert v.indices == sorted(v.indices)

    def test_encode_unknown_term(self):
        sv = Bm25SparseVectorizer()
        sv.fit(["apple banana"])
        v = sv.encode("zzzz")
        assert v.indices == []

    def test_empty_vocab_raises(self):
        sv = Bm25SparseVectorizer()
        with pytest.raises(RuntimeError):
            sv.encode("hello")


# ---------------------------------------------------------------------------
# VectorStore（Qdrant :memory: 真实例）
# ---------------------------------------------------------------------------

class TestQdrantVectorStore:
    @pytest.fixture
    def vs(self):
        v = QdrantVectorStore(location=":memory:")
        yield v

    @pytest.mark.asyncio
    async def test_dense_roundtrip(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.create_collection("c1", dim=4)
        await vs.upsert(
            "c1",
            ["id-1", "id-2"],
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
            [{"text": "a", "doc_id": "d1"}, {"text": "b", "doc_id": "d2"}],
        )
        res = await vs.search("c1", [1.0, 0.0, 0.0, 0.0], "a", top_k=2)
        assert len(res) == 2
        assert res[0][2]["doc_id"] == "d1"  # 最相似
        assert res[0][1] > res[1][1]

    @pytest.mark.asyncio
    async def test_filter(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.create_collection("c1", dim=2)
        await vs.upsert(
            "c1",
            ["a", "b"],
            [[1.0, 0.0], [0.0, 1.0]],
            [{"text": "x", "doc_id": "d1"}, {"text": "y", "doc_id": "d2"}],
        )
        res = await vs.search("c1", [1.0, 0.0], "x", top_k=5, filter_={"doc_id": "d2"})
        assert len(res) == 1
        assert res[0][2]["doc_id"] == "d2"

    @pytest.mark.asyncio
    async def test_scroll(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.create_collection("c1", dim=2)
        await vs.upsert(
            "c1",
            [f"id-{i}" for i in range(10)],
            [[1.0, 0.0]] * 10,
            [{"text": f"t{i}", "doc_id": f"d{i}"} for i in range(10)],
        )
        pts, offset = await vs.scroll("c1", limit=10)
        assert len(pts) == 10

    @pytest.mark.asyncio
    async def test_delete(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.create_collection("c1", dim=2)
        await vs.upsert("c1", ["a", "b"], [[1.0, 0.0], [0.0, 1.0]],
                        [{"text": "x"}, {"text": "y"}])
        await vs.delete("c1", ["a"])
        pts, _ = await vs.scroll("c1", limit=10)
        assert len(pts) == 1

    @pytest.mark.asyncio
    async def test_dim_mismatch(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.create_collection("c1", dim=4)
        with pytest.raises(ValueError):
            await vs.create_collection("c1", dim=8)

    @pytest.mark.asyncio
    async def test_hybrid_sparse(self):
        vs = QdrantVectorStore(location=":memory:", enable_sparse=True)
        await vs.create_collection("c1", dim=4)
        await vs.upsert(
            "c1",
            ["a", "b", "c"],
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            [{"text": "apple banana pie", "doc_id": "d1"},
             {"text": "apple cherry pie", "doc_id": "d2"},
             {"text": "grape wine", "doc_id": "d3"}],
        )
        res = await vs.search("c1", [1, 0, 0, 0], "apple pie", top_k=3)
        assert len(res) == 3
        # apple 相关的排前面（BM25 帮助召回）
        assert res[0][2]["doc_id"] in ("d1", "d2")

    @pytest.mark.asyncio
    async def test_close(self):
        vs = QdrantVectorStore(location=":memory:")
        await vs.close()