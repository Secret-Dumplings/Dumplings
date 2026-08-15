"""tangyuanAI plugin 子包：兼容 OpenAI ChatGPT Plugin 1.0 + Anthropic Claude Code Plugin。

详见 `plugin/manifest.py` / `plugin/fetcher.py` / `plugin/openapi.py` / `plugin/loader.py`。
"""
from .fetcher import FetcherError, GitHubSource, HTTPFetcher, LocalFetcher
from .loader import PluginSpec, can_handle, load_plugin
from .manifest import PluginManifest, parse_manifest

__all__ = [
    "PluginManifest",
    "parse_manifest",
    "PluginSpec",
    "load_plugin",
    "can_handle",
    "HTTPFetcher",
    "LocalFetcher",
    "GitHubSource",
    "FetcherError",
]
