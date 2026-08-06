# -*- coding: utf-8 -*-
"""tests/kb/ 共享 fixture：清理 KB 全局状态 + 注册 fake embedder。"""
from __future__ import annotations

import hashlib

import pytest
from tangyuanAI.kb.config import EmbedderConfig
from tangyuanAI.kb.embedder_base import BaseEmbedder


class FakeEmbedder(BaseEmbedder):
    """deterministic hash 向量（不连真 API）。"""
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


@pytest.fixture(autouse=True)
def _clean_kb(monkeypatch, tmp_path):
    """每个测试：清空 KB 注册表 + store cache + 全局缓存，隔离 Qdrant，注册 fake embedder。"""
    import tangyuanAI.kb.embedder_factory as factory
    from tangyuanAI.kb.cache import NullCache, get_global_cache, set_global_cache
    from tangyuanAI.kb.registry import _kbs, _store_cache, shutdown_all

    # 默认 base_dir 指向 tmp（隔离持久化）
    monkeypatch.setenv("TANGYUAN_KB_DIR", str(tmp_path))

    # 覆盖 openai-compatible → FakeEmbedder（测试隔离）
    factory._EMBEDDERS["openai-compatible"] = FakeEmbedder

    # 全局缓存换 NullCache（隔离缓存副作用）
    _orig_cache = get_global_cache()
    if not isinstance(_orig_cache, NullCache):
        set_global_cache(NullCache())

    saved = dict(_kbs)
    _kbs.clear()
    _store_cache.clear()

    yield

    # 清理后：关闭 Qdrant client + 还原
    shutdown_all()
    _kbs.update(saved)
    _store_cache.clear()
    if _orig_cache is not None:
        set_global_cache(_orig_cache)
    factory._EMBEDDERS["openai-compatible"] = __import__(
        "tangyuanAI.kb.embedder_openai", fromlist=["OpenAICompatibleEmbedder"]
    ).OpenAICompatibleEmbedder


def make_cfg(dim: int = 16, model: str = "fake-model", **kw) -> EmbedderConfig:
    """构造 FakeEmbedder 的 EmbedderConfig。"""
    base = dict(
        provider="openai-compatible", api_base="http://fake", model=model,
        embed_dim=dim, max_input_tokens=1000, batch_size=10,
    )
    base.update(kw)
    return EmbedderConfig(**base)
