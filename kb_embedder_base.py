# -*- coding: utf-8 -*-
"""
Knowledge Base 嵌入器抽象基类（kb_embedder_base.py）
====================================================

**职责**：所有 Embedder 实现共享的公共逻辑。

**提供**：
- token-aware batching：用 tiktoken 把文本按 token 数切批（不切单个文本）
- 缓存集成：自动 query / write LRUDiskCache
- 失败重试：tenacity 退避（429 / 5xx / 网络错误）
- 维度校验：API 返回的 vec 长度必须 == config.embed_dim
- 并发限流：asyncio.Semaphore(config.batch_size)

**抽象**（子类必须实现）：
- `_init_client()` → 初始化 provider 客户端（OpenAI SDK / cohere / httpx ...）
- `_embed_one_batch(batch)` → 真正调一次 API 返回 list[list[float]]

**复用**：
- 复用 `..kb_cache.make_cache_key` / `get_global_cache`
- 复用 `..kb_config.EmbedderConfig`
- 复用 `..logging_config.get_logger`
- 复用 `..kb_protocols.Embedder`（Protocol）
- 第三方：`tiktoken` / `tenacity`
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import tiktoken
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .kb_cache import get_global_cache, make_cache_key
from .kb_config import EmbedderConfig
from .errors import APIError


def get_logger(name: str):
    from .logging_config import get_logger as _real
    return _real(name)


__all__ = ["BaseEmbedder"]


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class EmbeddingError(APIError):
    """嵌入相关错误。继承 APIError 统一错误体系。"""


# ---------------------------------------------------------------------------
# 可重试的异常类型（tenacity 用）
# ---------------------------------------------------------------------------

_RETRYABLE_EXC = (APIError, ConnectionError, TimeoutError, OSError)


# ---------------------------------------------------------------------------
# BaseEmbedder
# ---------------------------------------------------------------------------

class BaseEmbedder(ABC):
    """所有 Embedder 实现继承此类。

    设计原则：
    - 缓存命中直接返回（不走 API）
    - token-aware 切批：按 max_input_tokens 累加，不切单个文本
    - asyncio.Semaphore 限流并发（batch_size）
    - tenacity 失败重试（429 / 5xx / 网络）
    - 维度校验（不一致报错）
    """

    # 子类覆盖：客户端名字（用于日志）
    client_name: str = "base"

    def __init__(
        self,
        config: EmbedderConfig,
        *,
        cache=None,
    ):
        self.config = config
        self.name: str = config.provider
        self.dim: int = config.embed_dim

        self._cache = cache if cache is not None else get_global_cache()
        self._semaphore = asyncio.Semaphore(config.batch_size)

        # tiktoken 编码器（cl100k_base 是 OpenAI 主流模型用的）
        try:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

        # 客户端懒初始化（子类实现）
        self._client = None
        try:
            self._client = self._init_client()
        except Exception as e:
            raise EmbeddingError(
                f"{self.client_name}: failed to init client: {e}"
            ) from e

        self._log = get_logger(f"kb.embedder.{self.client_name}")
        self._log.info(
            f"{self.client_name} ready: model={config.model} dim={config.embed_dim} "
            f"api_base={config.api_base} batch_size={config.batch_size}"
        )

    # === 子类实现 ===

    @abstractmethod
    def _init_client(self) -> Any:
        """初始化 provider client。返回 None 表示无可用客户端（如 offline-only）。"""
        ...

    @abstractmethod
    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        """**真正调一次 API**。返回维度 = self.dim 的向量列表（顺序与 batch 对应）。"""
        ...

    # === 公共 API ===

    async def embed(self, text: str) -> list[float]:
        """单条嵌入（带 cache + 重试 + 维度校验）。"""
        async with self._semaphore:
            key = self._cache_key(text)
            cached = await self._cache.get(key)
            if cached is not None:
                return cached

            result = await self._call_with_retry([text])
            vec = result[0]
            self._validate_dim(vec)
            try:
                await self._cache.set(key, vec)
            except Exception:
                pass
            return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入。

        流程：
        1. 查 cache（命中 → 直接返回）
        2. miss 部分按 token 数切批（每批总 token ≤ config.max_input_tokens * batch_size）
        3. 并发调用（受 semaphore 限流）
        4. 维度校验
        5. 写 cache
        """
        if not texts:
            return []

        # 1. 全部查 cache
        keys = [self._cache_key(t) for t in texts]
        cached_vecs = await asyncio.gather(*[self._cache.get(k) for k in keys])
        miss_idx = [i for i, v in enumerate(cached_vecs) if v is None]
        miss_texts = [texts[i] for i in miss_idx]

        if not miss_texts:
            return [v for v in cached_vecs if v is not None]  # type: ignore[misc]

        # 2. 切批（token-aware）
        batches = self._split_by_tokens(miss_texts)

        # 3. 并发调用（受 semaphore 限流）
        async def _one(b: list[str]) -> list[list[float]]:
            async with self._semaphore:
                return await self._call_with_retry(b)

        batch_results = await asyncio.gather(*[_one(b) for b in batches])

        # 4. 展平
        new_vecs: list[list[float]] = []
        for br in batch_results:
            for v in br:
                self._validate_dim(v)
                new_vecs.append(v)

        # 5. 写 cache
        for t, v in zip(miss_texts, new_vecs):
            key = self._cache_key(t)
            try:
                await self._cache.set(key, v)
            except Exception:
                pass

        # 6. 合并回原顺序
        result: list[list[float] | None] = list(cached_vecs)  # type: ignore[assignment]
        for idx, vec in zip(miss_idx, new_vecs):
            result[idx] = vec
        return [v for v in result if v is not None]  # type: ignore[misc]

    def max_batch_size(self) -> int:
        return self.config.batch_size

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

    def _cache_key(self, text: str) -> str:
        # 含 dim：同一模型名不同维度 → 不同 cache key（避免模型迁移时命中旧缓存）
        return make_cache_key(
            self.config.provider,
            self.config.api_base,
            self.config.model,
            text,
            dim=self.dim,
        )

    def _validate_dim(self, vec: list[float]) -> None:
        if len(vec) != self.config.embed_dim:
            raise EmbeddingError(
                f"{self.client_name}: dimension mismatch, got {len(vec)} expected "
                f"{self.config.embed_dim} for model {self.config.model!r}. "
                f"Check EmbedderConfig.embed_dim."
            )

    def _token_count(self, text: str) -> int:
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        # fallback：粗略估计 1 token ≈ 4 chars
        return max(1, len(text) // 4)

    def _split_by_tokens(self, texts: list[str]) -> list[list[str]]:
        """按 token 数切批：每批总 token ≤ max_input_tokens * batch_size。"""
        cap = self.config.max_input_tokens * self.config.batch_size
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0
        for t in texts:
            tk = self._token_count(t)
            # 单条超 max_input_tokens：单飞（不切单个文本）
            if tk > self.config.max_input_tokens:
                if current:
                    batches.append(current)
                    current, current_tokens = [], 0
                batches.append([t])
                continue
            if current_tokens + tk > cap and current:
                batches.append(current)
                current, current_tokens = [t], tk
            else:
                current.append(t)
                current_tokens += tk
        if current:
            batches.append(current)
        return batches

    async def _call_with_retry(self, batch: list[str]) -> list[list[float]]:
        """tenacity 退避重试 + 调 _embed_one_batch。"""
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
                            f" for batch size {len(batch)}"
                        )
                    return await self._embed_one_batch(batch)
        except _RETRYABLE_EXC as e:
            self._log.error(f"{self.client_name}: all retries failed: {e}")
            raise EmbeddingError(f"{self.client_name}: {e}") from e
        # 不会到这里
        raise EmbeddingError(f"{self.client_name}: unreachable")  # pragma: no cover

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.config.provider}, model={self.config.model!r}, dim={self.dim})"