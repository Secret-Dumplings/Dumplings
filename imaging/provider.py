# -*- coding: utf-8 -*-
"""tangyuanai.imaging —— 图片生成 Provider 抽象 + 通用 HttpJsonImageProvider 实现。

抽象接口：`ImageProvider` Protocol（满足结构化子类型）。
通用实现：`HttpJsonImageProvider` —— 读 config 的 `request_template`（带 `${var}` 占位符）+ `response_image_url_path`（JSON path）。
"""
from __future__ import annotations

import os
import re
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ImageProvider",
    "ImageError",
    "HttpJsonImageProvider",
    "render_template",
    "resolve_json_path",
    "resolve_url_template",
    "download_urls",
]


class ImageError(Exception):
    """图片生成相关错误。"""


@runtime_checkable
class ImageProvider(Protocol):
    """图片生成 Provider 接口（满足结构化子类型）。"""
    name: str

    async def generate(
        self, *, prompt: str, model: str | None = None, **kwargs: Any
    ) -> list[str]:
        """返回图片 URL 列表（URL 1 小时过期，调用方须下载）。"""
        ...

    async def close(self) -> None:
        """关闭 client（释放 httpx 连接池）。"""
        ...


# ---------------------------------------------------------------------------
# 模板 / 路径 / URL 工具
# ---------------------------------------------------------------------------

def render_template(template: Any, vars: dict) -> Any:
    """递归渲染模板：${var} → vars[var]（None 跳过该字段）。

    - dict：逐 key 渲染 value（None 跳过）
    - list：逐元素渲染
    - str：纯字符串返回；若匹配 `${var}` 且 vars[var] is None → 返回 None（让调用方 drop）
    - 其它：原样返回
    """
    if isinstance(template, dict):
        out: dict[str, Any] = {}
        for k, v in template.items():
            r = render_template(v, vars)
            if r is not None:
                out[k] = r
        return out
    if isinstance(template, list):
        return [render_template(v, vars) for v in template]
    if isinstance(template, str):
        s = template
        if s.startswith("${") and s.endswith("}"):
            var_name = s[2:-1]
            val = vars.get(var_name)
            return val if val is not None else None
        return s
    return template


def resolve_json_path(data: Any, path: str) -> Any:
    """点路径 + 数字索引 解析 JSON（'data.0.url' → data[0]['url']）。"""
    cur = data
    if not path:
        return cur
    for token in path.split("."):
        if cur is None:
            return None
        if token.isdigit():
            try:
                cur = cur[int(token)]
            except (IndexError, ValueError, TypeError):
                return None
        else:
            cur = cur.get(token) if isinstance(cur, dict) else None
    return cur


def resolve_url_template(api_base: str, env: dict | None = None) -> str:
    """把 `${env:VAR}` 替换为 env[VAR]（env 默认 os.environ）。"""
    e = env if env is not None else os.environ
    return re.sub(r"\$\{env:(\w+)\}", lambda m: e.get(m.group(1), ""), api_base)


# ---------------------------------------------------------------------------
# 本地下载（URL 1 小时过期 → 落盘）
# ---------------------------------------------------------------------------

async def download_urls(
    urls: list[str], download_dir: str, *,
    ext: str = ".png",
    timeout: float = 60.0,
) -> list[str]:
    """并发下载 URL 列表到本地目录，返回本地路径列表。

    - 文件名用 URL 的 sha256[:16] + ext（去重）
    - 已存在跳过（避免重下）
    - httpx 复用 http_utils.AsyncHTTPClient
    """
    import asyncio
    import hashlib
    from pathlib import Path as _Path

    from ..http_utils import AsyncHTTPClient

    p = _Path(download_dir)
    p.mkdir(parents=True, exist_ok=True)
    client = AsyncHTTPClient(timeout=timeout)
    try:
        async def _one(u: str) -> str:
            name = hashlib.sha256(u.encode()).hexdigest()[:16] + ext
            local = p / name
            if local.exists():
                return str(local)
            r = await client.client.get(u)
            r.raise_for_status()
            local.write_bytes(r.content)
            return str(local)
        return list(await asyncio.gather(*[_one(u) for u in urls]))
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 通用 HttpJsonImageProvider：所有 provider 共用
# ---------------------------------------------------------------------------

class HttpJsonImageProvider:
    """通用 HTTP JSON 图片生成 provider。

    读 feature_cfg：
    - api_base（支持 ${env:VAR} 占位符）
    - api_key（从 cfg["api_key_env"] env 读）
    - request_template（JSON 模板 + ${var} 占位符）
    - response_image_url_path（JSON path 表达式）
    - request_static（可选：每次请求都带的静态字段）
    - default_model（可选）
    """
    name = "http_json"

    def __init__(self, *, name: str, feature_cfg: dict):
        import httpx

        from ..http_utils import AsyncHTTPClient
        from ..logging_config import get_logger

        self.name = name
        self._cfg = feature_cfg
        self._api_base = resolve_url_template(
            feature_cfg["api_base"], os.environ
        )
        key_env = feature_cfg.get("api_key_env")
        if not key_env:
            raise ImageError(
                f"feature 缺 api_key_env 字段（provider={name!r}）"
            )
        self._api_key = os.environ.get(key_env)
        if not self._api_key:
            raise ImageError(
                f"env {key_env!r} 未设置（image provider {name!r} 需要）"
            )
        # 鉴权可配置（零修改兼容更多厂商）：
        #   auth_header  header 名（默认 Authorization）
        #   auth_prefix  header 值前缀（默认 "Bearer "）
        #   auth_scheme  "bearer"（默认，带 auth_header+auth_prefix）| "none"（不带鉴权头）
        self._auth_scheme = feature_cfg.get("auth_scheme", "bearer")
        self._auth_header = feature_cfg.get("auth_header", "Authorization")
        self._auth_prefix = feature_cfg.get("auth_prefix", "Bearer ")
        http = httpx.AsyncClient(
            base_url=self._api_base,
            timeout=feature_cfg.get("timeout", 60.0),
        )
        self._client = AsyncHTTPClient(
            client=http,
            default_timeout=feature_cfg.get("timeout", 60.0),
        )
        self._log = get_logger("imaging.http_json")

    async def generate(
        self, *, prompt: str, model: str | None = None, **kwargs: Any,
    ) -> list[str]:
        # model 缺省用 config 的 default_model
        model = model or self._cfg.get("default_model")
        body = render_template(
            self._cfg.get("request_template", {}),
            {"prompt": prompt, "model": model, **kwargs},
        )
        if body is None:
            body = {}
        # 合并静态字段（不被模板覆盖）
        for k, v in self._cfg.get("request_static", {}).items():
            body.setdefault(k, v)

        # 鉴权头（可配置）
        headers = {}
        if self._auth_scheme != "none":
            headers[self._auth_header] = f"{self._auth_prefix}{self._api_key}"

        resp = await self._client.apost(
            "",
            json=body,
            headers=headers,
        )
        data = resp.json()
        path = self._cfg["response_image_url_path"]
        url = resolve_json_path(data, path)
        if isinstance(url, list):
            # 响应 path 指向 URL 数组（如 data.image_urls）
            return [u for u in url if isinstance(u, str) and u]
        if not url:
            # fallback：常见 OpenAI images 风格
            return [
                item["url"] for item in data.get("data", [])
                if item.get("url")
            ]
        return [url] if isinstance(url, str) else [str(url)]

    async def close(self):
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
