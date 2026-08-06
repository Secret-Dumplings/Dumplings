# -*- coding: utf-8 -*-
"""
Knowledge Base 配置模型（kb_config.py）
=======================================

**职责**：`EmbedderConfig` 和 `RerankerConfig` 两个 pydantic 模型，**用户驱动的 Provider+API 配置**。

**核心约定（v5 起，用户钦定）**：
- 不维护静态 MODEL_CATALOG
- 用户自己填 provider / api_base / model / embed_dim / max_input_tokens
- 换 provider = 改 config（不改代码）

**复用**：
- 复用 `..errors.APIError`（作为运行时异常基类）
- 复用 `..logging_config.get_logger`（debug 日志）
- **不复用**任何 LLM 的 OpenAI / Anthropic 配置（这是 KB 自己的 API config）
"""
from __future__ import annotations

import os
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# EmbedderConfig
# ---------------------------------------------------------------------------

EmbedderProvider = Literal[
    "openai",            # OpenAI 官方
    "openai-compatible", # 任何 OpenAI 兼容端点（Ollama / vLLM / Xinference / LM Studio / 私网关）
    "cohere",
    "voyage",
    "jina",
]


class EmbedderConfig(BaseModel):
    """嵌入模型配置：provider + api_base + model + embed_dim。

    **必填**：provider / api_base / model / embed_dim
    **选填**：api_key（默认从 env 读 TANGYUAN_<PROVIDER>_API_KEY）/ max_input_tokens / batch_size / extra_headers / timeout / max_retries
    """
    model_config = ConfigDict(extra="forbid")

    provider: EmbedderProvider
    api_base: str = Field(..., min_length=1, description="API base URL，例如 https://api.openai.com/v1")
    model: str = Field(..., min_length=1, description="模型名，例如 text-embedding-3-small")
    api_key: Optional[str] = Field(None, description="API key；None 时从 env TANGYUAN_<PROVIDER>_API_KEY 读")
    embed_dim: int = Field(..., ge=1, description="嵌入维度；用户必须知道（provider 不能探测）")
    max_input_tokens: int = Field(8191, ge=1, le=200_000, description="单条文本最大 token 数")
    batch_size: int = Field(100, ge=1, le=1000, description="推荐批大小")
    extra_headers: dict[str, str] = Field(default_factory=dict, description="自定义请求头（X-Tenant-Id / 鉴权 / 网关等）")
    timeout: float = Field(60.0, gt=0, description="单次请求超时（秒）")
    max_retries: int = Field(3, ge=0, le=10, description="失败重试次数（429 / 5xx）")

    @model_validator(mode="after")
    def _check_api_base(self) -> "EmbedderConfig":
        api_base = self.api_base.strip().rstrip("/")
        if not api_base.startswith(("http://", "https://")):
            raise ValueError(f"api_base must start with http:// or https://, got {self.api_base!r}")
        # 标准化（去末尾 /）
        object.__setattr__(self, "api_base", api_base)
        return self

    def env_var_name(self) -> str:
        """对应的环境变量名。"""
        return f"TANGYUAN_{self.provider.upper().replace('-', '_')}_API_KEY"

    def resolve_api_key(self) -> str:
        """解析 API key：先显式 api_key，再 env，最后空串。"""
        if self.api_key:
            return self.api_key
        env = os.environ.get(self.env_var_name(), "")
        if env:
            return env
        # OpenAI 兼容（Ollama / vLLM 等本地）允许无 key
        if self.provider in ("openai-compatible", "openai"):
            return "EMPTY"
        return ""

    def __repr__(self) -> str:
        return (
            f"EmbedderConfig(provider={self.provider!r}, api_base={self.api_base!r}, "
            f"model={self.model!r}, embed_dim={self.embed_dim})"
        )


# ---------------------------------------------------------------------------
# RerankerConfig
# ---------------------------------------------------------------------------

RerankerProvider = Literal[
    "no-op",               # 默认占位，不重排
    "openai-compatible",   # 任何暴露 /v1/rerank 的端点（vLLM / Cohere-via-proxy / 自家）
    "cohere",
    "voyage",
    "jina",
    "bge-local",           # sentence-transformers CrossEncoder（本地推理）
    "colbert",             # ColBERT v2（本地）
    "monot5",              # MonoT5（本地）
]


class RerankerConfig(BaseModel):
    """重排模型配置：provider + api_base + model。

    **必填**：provider
    **remote provider 必填**：api_base / model
    **local provider 必填**：model_path（本地模型路径）或 model（HuggingFace 名字）
    """
    model_config = ConfigDict(extra="forbid")

    provider: RerankerProvider
    api_base: Optional[str] = Field(None, description="远程 provider 必填")
    model: Optional[str] = Field(None, description="模型名（远程）或 HuggingFace 模型名（本地）")
    api_key: Optional[str] = Field(None, description="远程 provider 的 API key")
    model_path: Optional[str] = Field(None, description="本地 provider 的模型路径（优先于 model）")
    max_input_tokens: int = Field(512, ge=1, le=10_000, description="query + chunk pair 的最大 token")
    batch_size: int = Field(64, ge=1, le=1000)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(60.0, gt=0)
    max_retries: int = Field(3, ge=0, le=10)

    @model_validator(mode="after")
    def _check_provider(self) -> "RerankerConfig":
        if self.provider == "no-op":
            return self

        # 远程 provider：api_base + model 必填
        if self.provider in ("openai-compatible", "cohere", "voyage", "jina"):
            if not self.api_base:
                raise ValueError(f"provider={self.provider!r} requires api_base")
            if not self.model:
                raise ValueError(f"provider={self.provider!r} requires model")
            api_base = self.api_base.strip().rstrip("/")
            if not api_base.startswith(("http://", "https://")):
                raise ValueError(f"api_base must start with http:// or https://, got {self.api_base!r}")
            object.__setattr__(self, "api_base", api_base)

        # 本地 provider：model_path 或 model 必填
        elif self.provider in ("bge-local", "colbert", "monot5"):
            if not self.model and not self.model_path:
                raise ValueError(
                    f"provider={self.provider!r} requires model_path (local file path) "
                    "or model (HuggingFace model name)"
                )
            if self.api_base:
                # 本地 provider 不需要 api_base
                pass

        return self

    def env_var_name(self) -> str:
        return f"TANGYUAN_{self.provider.upper().replace('-', '_')}_API_KEY"

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        env = os.environ.get(self.env_var_name(), "")
        if env:
            return env
        if self.provider == "openai-compatible":
            return "EMPTY"
        return ""

    def resolve_model_path(self) -> str:
        """本地 provider 用：优先 model_path，再 model。"""
        if self.model_path:
            return self.model_path
        if self.model:
            return self.model
        raise ValueError(f"provider={self.provider!r} requires model_path or model")

    def __repr__(self) -> str:
        if self.provider == "no-op":
            return "RerankerConfig(provider='no-op')"
        return (
            f"RerankerConfig(provider={self.provider!r}, "
            f"api_base={self.api_base!r}, model={self.model!r})"
        )


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

__all__ = [
    "EmbedderConfig",
    "EmbedderProvider",
    "RerankerConfig",
    "RerankerProvider",
]