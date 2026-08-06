# -*- coding: utf-8 -*-
"""
Reranker 工厂（kb_reranker_factory.py）
=======================================

**新增 provider**：在 `kb_reranker_<provider>.py` 创建类，在本文件 `_RERANKERS` dict 加一行。
"""
from __future__ import annotations

from .kb_config import RerankerConfig
from .kb_protocols import Reranker
from .kb_reranker_noop import NoOpReranker
from .kb_reranker_openai import OpenAICompatibleReranker
from .kb_reranker_cohere import CohereReranker
from .kb_reranker_jina import JinaReranker
from .kb_reranker_bge import BGEReranker
from .kb_reranker_colbert import ColBERTReranker
from .kb_reranker_monot5 import MonoT5Reranker


__all__ = ["create_reranker", "list_reranker_providers"]


_RERANKERS = {
    "no-op": NoOpReranker,
    "openai-compatible": OpenAICompatibleReranker,
    "cohere": CohereReranker,
    "jina": JinaReranker,
    "bge-local": BGEReranker,
    "colbert": ColBERTReranker,
    "monot5": MonoT5Reranker,
}


def create_reranker(config: RerankerConfig, *, cache=None) -> Reranker:
    cls = _RERANKERS.get(config.provider)
    if cls is None:
        raise ValueError(
            f"Unknown reranker provider: {config.provider!r}. "
            f"Available: {sorted(_RERANKERS)}"
        )
    return cls(config, cache=cache)


def list_reranker_providers() -> list[str]:
    return sorted(_RERANKERS)