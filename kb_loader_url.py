# -*- coding: utf-8 -*-
"""
URL Loader（kb_loader_url.py）
==============================

**职责**：拉取远程 URL → 提取正文文本（beautifulsoup4 + lxml 清洗）。

**复用**：
- `..http_utils.HTTPClient`（统一 HTTP + 重试 + 错误分类）
- `beautifulsoup4` + `lxml`（已 required dep）

注意：Loader 是同步协议，URL 拉取用 `http_utils.HTTPClient`（sync），
不能在 async context 里调用 `asyncio.run()`。
"""
from __future__ import annotations

from typing import Any

from .kb_loader_base import BaseLoader


__all__ = ["URLLoader"]

_MAX_URL_SIZE = 10 * 1024 * 1024  # 10 MB


class URLLoader(BaseLoader):
    """远程 URL 加载。"""
    name = "url"

    def __init__(self, *, timeout: float = 30.0, max_size: int = _MAX_URL_SIZE):
        self.timeout = timeout
        self.max_size = max_size

    def can_handle(self, source: str) -> bool:
        return source.startswith(("http://", "https://"))

    def _load(self, source: str) -> list[tuple[str, str, dict[str, Any]]]:
        from .http_utils import HTTPClient

        client = HTTPClient(default_timeout=self.timeout)
        try:
            r = client.get(source)
        finally:
            # HTTPClient 不强制关闭；每次 new 一个（httpx.Client 非线程安全）
            pass

        if r.status_code != 200:
            raise RuntimeError(f"URL fetch failed: {source} -> HTTP {r.status_code}")
        if len(r.content) > self.max_size:
            raise RuntimeError(
                f"URL too large ({len(r.content)} bytes > {self.max_size}): {source}"
            )

        content_type = r.headers.get("content-type", "")
        text = r.text if "html" in content_type else r.content.decode("utf-8", errors="replace")

        # HTML 清洗 → 正文
        if "html" in content_type.lower():
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()
            text = "\n\n".join(
                p.get_text(" ", strip=True)
                for p in soup.find_all(["p", "h1", "h2", "h3", "li", "pre", "blockquote"])
                if p.get_text(strip=True)
            )

        return [(text, source, {"url": source, "content_type": content_type})]