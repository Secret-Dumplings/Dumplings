# -*- coding: utf-8 -*-
"""
Cohere Embedder（kb_embedder_cohere.py）
=========================================

**依赖**：`cohere>=5.5`（optional dep `[kb-embed-cohere]`）。
未安装时 create_embedder 会抛 ImportError，引导用户装。
"""
from __future__ import annotations

from typing import Any

from .kb_embedder_base import BaseEmbedder
from .kb_config import EmbedderConfig


__all__ = ["CohereEmbedder"]


class CohereEmbedder(BaseEmbedder):
    """Cohere 嵌入器（embed-english-v3.0 / embed-multilingual-v3.0 等）。"""
    client_name = "cohere"

    def _init_client(self) -> Any:
        try:
            import cohere
        except ImportError as e:
            raise ImportError(
                "cohere SDK not installed. Run `pip install tangyuanAI[kb-embed-cohere]`."
            ) from e

        return cohere.AsyncClient(
            api_key=self.config.resolve_api_key(),
            base_url=self.config.api_base,
        )

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        resp = await self._client.embed(
            texts=batch,
            model=self.config.model,
            input_type="search_document",
            embedding_types=["float"],
        )
        # cohere v5: resp.embeddings.float_  (list[list[float]])
        return list(resp.embeddings.float_)