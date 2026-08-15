# -*- coding: utf-8 -*-
"""tangyuanai.plugin.fetcher —— 两种 fetcher 把外部 manifest 拿到本地 JSON 内容。

**核心**：OpenAI 和 Anthropic 都**降级到 JSON 文件解析**，差别只在「怎么拿 JSON 内容」。

- `HTTPFetcher(url)`：OpenAI ChatGPT Plugin 1.0。GET `{url}/.well-known/ai-plugin.json` + 拉 OpenAPI spec。
- `LocalFetcher(path)`：Anthropic Claude Code Plugin。读 `{path}/.claude-plugin/plugin.json` + 可选 `.mcp.json` + skills 目录。
- `GitHubSource(name)`：旧入口（中央仓库 `<name>.json`），向后兼容 v1.3.0 删除。

fetcher 只负责拿 JSON 内容；后续解析 / sub-component 加载走 `loader.py`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from tangyuanAI.logging_config import get_logger

from .manifest import PluginManifest, parse_manifest

_logger = get_logger("plugin.fetcher")

__all__ = ["HTTPFetcher", "LocalFetcher", "GitHubSource", "FetcherError"]


class FetcherError(RuntimeError):
    """fetcher 失败（HTTP 4xx/5xx / 文件不存在 / JSON 解析失败）。"""


class HTTPFetcher:
    """OpenAI ChatGPT Plugin 1.0 fetcher。

    Usage::

        spec = HTTPFetcher("https://example.com").fetch()
    """

    WELL_KNOWN_PATH = "/.well-known/ai-plugin.json"

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    @property
    def manifest_url(self) -> str:
        return f"{self.base_url}{self.WELL_KNOWN_PATH}"

    def fetch(self) -> PluginManifest:
        from tangyuanAI.http_utils import AsyncHTTPClient

        client = AsyncHTTPClient(timeout=self.timeout)
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            async def _do() -> PluginManifest:
                rsp = await client.apost(self.manifest_url, json=None, headers={"Accept": "application/json"})
                if not (200 <= rsp.status_code < 300):
                    raise FetcherError(
                        f"HTTP {rsp.status_code} fetching {self.manifest_url}: {rsp.text[:200]}"
                    )
                text = rsp.text
                api_spec_url = self._parse_and_extract_openapi_url(text)
                manifest = parse_manifest(
                    text,
                    source="openai",
                    manifest_path=self.manifest_url,
                )
                if api_spec_url:
                    openapi_text = await self._fetch_openapi(client, api_spec_url)
                    manifest.openapi_spec = json.loads(openapi_text)
                return manifest

            if loop is None:
                return asyncio.run(_do())
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, _do()).result()
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _parse_and_extract_openapi_url(manifest_text: str) -> Optional[str]:
        try:
            data = json.loads(manifest_text)
        except json.JSONDecodeError:
            return None
        api = data.get("api") or {}
        if api.get("type") == "openapi" and api.get("url"):
            return api["url"]
        return None

    @staticmethod
    async def _fetch_openapi(client, url: str) -> str:
        from urllib.parse import urlparse
        # 用 GET；manifest 里的 api.url 可能是相对路径
        if not urlparse(url).netloc:
            # 相对路径 → 拼 base_url
            base = urlparse(client.client.base_url if hasattr(client, "client") else "")
            url = f"{base.scheme}://{base.netloc}{url}"
        rsp = await client.apost(url, json=None, headers={"Accept": "application/yaml, application/json"})
        if not (200 <= rsp.status_code < 300):
            raise FetcherError(f"HTTP {rsp.status_code} fetching OpenAPI {url}")
        return rsp.text


class LocalFetcher:
    """Anthropic Claude Code Plugin fetcher。

    Usage::

        spec = LocalFetcher("./my-plugin").fetch()      # 读 .claude-plugin/plugin.json
        spec = LocalFetcher("./my-plugin/.claude-plugin/plugin.json").fetch()  # 直接读 manifest
    """

    def __init__(self, plugin_dir_or_manifest: str):
        self._target = Path(plugin_dir_or_manifest).expanduser().resolve()

    def fetch(self) -> PluginManifest:
        # 自动定位 manifest 路径
        if self._target.is_file() and self._target.name == "plugin.json":
            manifest_file = self._target
            plugin_root = self._target.parent.parent  # .claude-plugin/ → parent
        elif self._target.is_dir():
            manifest_file = self._target / ".claude-plugin" / "plugin.json"
            plugin_root = self._target
        else:
            raise FetcherError(f"Plugin 路径不存在：{self._target}")

        if not manifest_file.exists():
            raise FetcherError(
                f"未找到 .claude-plugin/plugin.json（应位于 {manifest_file.parent}）"
            )

        text = manifest_file.read_text(encoding="utf-8")
        manifest = parse_manifest(
            text,
            source="anthropic",
            manifest_path=str(manifest_file),
            plugin_root=str(plugin_root),
        )
        return manifest


class GitHubSource:
    """旧 entry：中央仓库 `<name>.json` feature config（向后兼容）。

    走 `plugin_store.fetch_plugin_config` 拉 JSON；merge 进 `tangyuanai.config.json`。
    v1.3.0 删除；新代码用 `LocalFetcher` / `HTTPFetcher`。
    """

    def __init__(self, plugin_name: str, *, owner: str = "secret-tangyuan",
                 repo: Optional[str] = None, branch: str = "main"):
        self.plugin_name = plugin_name
        self.owner = owner
        self.repo = repo or self._default_repo(plugin_name)
        self.branch = branch

    @staticmethod
    def _default_repo(name: str) -> str:
        from tangyuanAI.plugin_store import DEFAULT_REPO, PLUGIN_REPO_MAP
        return PLUGIN_REPO_MAP.get(name, DEFAULT_REPO)

    def fetch(self) -> dict[str, Any]:
        """返回原始 feature config dict（不是 PluginManifest）。"""
        import asyncio

        from tangyuanAI.plugin_store import fetch_plugin_config

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _do() -> dict[str, Any]:
            return await fetch_plugin_config(
                self.plugin_name, owner=self.owner, repo=self.repo, branch=self.branch,
            )

        if loop is None:
            return asyncio.run(_do())
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _do()).result()
