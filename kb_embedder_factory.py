# -*- coding: utf-8 -*-
"""
Embedder 工厂（kb_embedder_factory.py）
=======================================

**职责**：根据 `EmbedderConfig.provider` 字符串分派到具体实现。

**新增 provider**：
1. 在 `kb_embedder_<provider>.py` 创建 `XxxEmbedder(BaseEmbedder)`
2. 在本文件的 `_EMBEDDERS` dict 加一行 `"<provider>": XxxEmbedder`

**其他文件不用改**（多文件差分的好处）。
"""
from __future__ import annotations

from .kb_config import EmbedderConfig
from .kb_protocols import Embedder
from .kb_embedder_openai import OpenAICompatibleEmbedder
from .kb_embedder_cohere import CohereEmbedder
from .kb_embedder_jina import JinaEmbedder
from .kb_embedder_voyage import VoyageEmbedder


__all__ = ["create_embedder", "list_embedder_providers"]


_EMBEDDERS = {
    "openai": OpenAICompatibleEmbedder,
    "openai-compatible": OpenAICompatibleEmbedder,
    "cohere": CohereEmbedder,
    "jina": JinaEmbedder,
    "voyage": VoyageEmbedder,
}


def create_embedder(config: EmbedderConfig, *, cache=None) -> Embedder:
    """根据 provider 创建 embedder 实例。"""
    cls = _EMBEDDERS.get(config.provider)
    if cls is None:
        raise ValueError(
            f"Unknown embedder provider: {config.provider!r}. "
            f"Available: {sorted(_EMBEDDERS)}"
        )
    return cls(config, cache=cache)


def list_embedder_providers() -> list[str]:
    """列出所有可用的 embedder provider。"""
    return sorted(_EMBEDDERS)