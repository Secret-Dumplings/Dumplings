# -*- coding: utf-8 -*-
"""
Knowledge Base 重排器抽象基类（kb_reranker_base.py）
====================================================

**职责**：所有 Reranker 实现共享的公共逻辑。

**提供**：
- query + chunk pair 的 token-aware batching
- 缓存集成
- 失败重试（tenacity）
- 排序 + 截 top_k

**抽象**（子类必须实现）：
- `_init_model()` → 初始化客户端 / 本地模型
- `_rerank_one_batch(query, chunks)` → 返回 [(chunk, score), ...]，按 score 降序

**复用**：
- 复用 `..kb_cache.make_cache_key`
- 复用 `..kb_config.RerankerConfig`
- 复用 `..logging_config.get_logger`
- 复用 `..kb_protocols.Reranker`
"""
from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from typing import Any

import tiktoken
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .kb_cache import get_global_cache
from .kb_config import RerankerConfig
from .kb_types import Chunk
from .errors import APIError


def get_logger(name: str):
    from .logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseReranker", "RerankerError"]


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class RerankerError(APIError):
    """重排相关错误。"""


_RETRYABLE_EXC = (APIError, ConnectionError, TimeoutError, OSError)


# ---------------------------------------------------------------------------
# BaseReranker
# ---------------------------------------------------------------------------

class BaseReranker(ABC):
    """所有 Reranker 实现继承此类。"""

    client_name: str = "base"

    def __init__(self, config: RerankerConfig, *, cache=None):
        self.config = config
        self.name: str = config.provider

        self._cache = cache if cache is not None else get_global_cache()
        self._semaphore = asyncio.Semaphore(config.batch_size)

        try:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

        try:
            self._client = self._init_model()
        except Exception as e:
            raise RerankerError(f"{self.client_name}: failed to init: {e}") from e

        self._log = get_logger(f"kb.reranker.{self.client_name}")
        self._log.info(f"{self.client_name} ready: provider={config.provider}")

    # === 子类实现 ===

    @abstractmethod
    def _init_model(self) -> Any:
        """初始化 client / 本地模型。"""
        ...

    @abstractmethod
    async def _rerank_one_batch(
        self, query: str, chunks: list[Chunk]
    ) -> list[tuple[Chunk, float]]:
        """对 (query, chunks) 打分；返回 [(chunk, score), ...]，按 score 降序。

        重要：返回的 chunks 必须来自入参（不要新建），方便我们排序 + dedup。
        """
        ...

    # === 公共 API ===

    async def rerank(
        self, query: str, chunks: list[Chunk], top_k: int
    ) -> list[tuple[Chunk, float]]:
        """重排。

        1. 全部查 cache
        2. miss 部分按 token-aware 切批
        3. 并发调用
        4. 合并所有打分
        5. 排序取 top_k
        6. 写 cache
        """
        if not chunks:
            return []
        if top_k <= 0:
            return []

        # 1. 查 cache
        cached_pairs = await asyncio.gather(*[
            self._cache.get(self._cache_key(query, c.id)) for c in chunks
        ])
        # 替换为已缓存的分数
        scored: list[tuple[Chunk, float]] = []
        miss_idx: list[int] = []
        for i, (c, cached) in enumerate(zip(chunks, cached_pairs)):
            if cached is not None and len(cached) == 1:
                scored.append((c, float(cached[0])))
            else:
                miss_idx.append(i)

        if not miss_idx:
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

        miss_chunks = [chunks[i] for i in miss_idx]

        # 2. token-aware 切批
        batches = self._split_by_tokens(query, miss_chunks)

        # 3. 并发调用
        async def _one(b: list[Chunk]) -> list[tuple[Chunk, float]]:
            async with self._semaphore:
                return await self._call_with_retry(query, b)

        batch_results = await asyncio.gather(*[_one(b) for b in batches])

        # 4. 合并
        for br in batch_results:
            for c, s in br:
                scored.append((c, s))
                # 5. 写 cache
                try:
                    await self._cache.set(
                        self._cache_key(query, c.id), [float(s)]
                    )
                except Exception:
                    pass

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            try:
                close_meth = self._client.close
                if asyncio.iscoroutinefunction(close_meth):
                    await close_meth()
                else:
                    close_meth()
            except Exception:
                pass

    # === 内部 ===

    def _cache_key(self, query: str, chunk_id: str) -> str:
        # rerank 缓存 key = sha256(provider|api_base|model|query|chunk_id|text_hash)
        # 注意 chunk 内容变化时（重切分）需要 cache miss → 用 chunk_id 不够，加文本 hash
        # 但我们只能拿到 chunk_id（chunk.text 在外面），所以用 query + chunk_id 作为 key（够用：chunk_id 唯一）
        raw = f"rerank|{self.config.provider}|{self.config.api_base}|{self.config.model}|{query}|{chunk_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _token_count(self, text: str) -> int:
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        return max(1, len(text) // 4)

    def _split_by_tokens(self, query: str, chunks: list[Chunk]) -> list[list[Chunk]]:
        """按 (query + chunk.text) token 总和切批。"""
        q_tokens = self._token_count(query)
        # 单批可用 token = max_input_tokens * batch_size - query tokens（query 每个 batch 都算一次）
        per_batch_cap = self.config.max_input_tokens * self.config.batch_size - q_tokens

        batches: list[list[Chunk]] = []
        current: list[Chunk] = []
        current_tokens = 0
        for c in chunks:
            tk = self._token_count(c.text)
            # 单 chunk 超 max_input_tokens：单飞
            if tk > self.config.max_input_tokens:
                if current:
                    batches.append(current)
                    current, current_tokens = [], 0
                batches.append([c])
                continue
            if current_tokens + tk > per_batch_cap and current:
                batches.append(current)
                current, current_tokens = [c], tk
            else:
                current.append(c)
                current_tokens += tk
        if current:
            batches.append(current)
        return batches

    async def _call_with_retry(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.config.max_retries + 1),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
                retry=retry_if_exception_type(_RETRYABLE_EXC),
                reraise=True,
            ):
                with attempt:
                    if attempt.retry_state.attempt_number > 1:
                        self._log.warning(
                            f"{self.client_name}: retry {attempt.retry_state.attempt_number - 1}"
                            f" for batch size {len(chunks)}"
                        )
                    return await self._rerank_one_batch(query, chunks)
        except _RETRYABLE_EXC as e:
            self._log.error(f"{self.client_name}: all retries failed: {e}")
            raise RerankerError(f"{self.client_name}: {e}") from e
        raise RerankerError(f"{self.client_name}: unreachable")  # pragma: no cover

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.config.provider}, model={self.config.model!r})"