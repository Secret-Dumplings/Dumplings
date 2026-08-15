# -*- coding: utf-8 -*-
"""tangyuanai.plugin_store —— 插件 config 安装：下载 + 合并本地 tangyuanai.config.json。

插件有两层：
1. **代码包**（pip 包，entry point ``tangyuanai.plugins`` 注册）—— 提供实现 + 内置 config
2. **config**（本文件处理）—— 合并到本地 ``tangyuanai.config.json`` 的 features 列表

``tangyuanai plugin install <name>`` 流程：
- 若代码包已安装 → 直接取包内置 ``PLUGIN_CONFIGS``（离线可用）
- 否则 → 从中央 config 仓库下载 ``<name>.json``（GitHub raw）

中央仓库：
- 图片插件：https://github.com/secret-tangyuan/tangyuanAI_image_plus
- RAG 插件：https://github.com/secret-tangyuan/tangyuanAI_RAG_plus
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import load_config, merge_feature, save_config
from .logging_config import logger

__all__ = ["install_plugin", "list_installed", "fetch_plugin_config"]

#: 默认中央仓库 owner / branch
DEFAULT_OWNER = "secret-tangyuan"
DEFAULT_BRANCH = "main"

#: 已知插件名 → 中央 config 仓库 repo 名（CLI 不带 --repo 时自动匹配）
PLUGIN_REPO_MAP: dict[str, str] = {
    # 图片插件（tangyuanAI_image_plus）
    "image_generation": "tangyuanAI_image_plus",
    "image_generation_dashscope": "tangyuanAI_image_plus",
    "image_generation_minimax": "tangyuanAI_image_plus",
    "image_generation_doubao": "tangyuanAI_image_plus",
    # RAG / 知识库插件（tangyuanAI_RAG_plus）
    "rag": "tangyuanAI_RAG_plus",
    "kb": "tangyuanAI_RAG_plus",
}

#: 兼容旧版默认值
DEFAULT_REPO = "tangyuanAI_image_plus"

# raw URL 模板
_CENTRAL_REPO_URL = (
    "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{plugin_name}.json"
)


def _repo_for(plugin_name: str, repo: Optional[str]) -> str:
    if repo:
        return repo
    return PLUGIN_REPO_MAP.get(plugin_name, DEFAULT_REPO)


async def fetch_plugin_config(
    plugin_name: str,
    *,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """从中央仓库下载 plugin config JSON。

    期望 JSON 格式（一个 plugin 一个文件）：
    {
      "name": "image_generation",
      "type": "image_generation",
      "config": { ... feature["config"] 全部 ... }
    }
    """
    url = _CENTRAL_REPO_URL.format(
        owner=owner, repo=repo, branch=branch, plugin_name=plugin_name
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _builtin_configs_for(plugin_name: str) -> list[dict[str, Any]]:
    """在所有已安装插件包的 PLUGIN_CONFIGS 里，按 feature name 匹配 config。

    例如插件 entry point 名是 ``image``，但 config 名叫 ``image_generation``，
    也要能命中（离线安装不需要下载）。
    """
    from .plugin_loader import discover_plugins, load_plugin

    out: list[dict[str, Any]] = []
    for name in discover_plugins():
        try:
            mod = load_plugin(name)
        except Exception:
            continue
        for f in getattr(mod, "PLUGIN_CONFIGS", []) or []:
            if f.get("name") == plugin_name:
                out.append(f)
    return out


async def install_plugin(
    plugin_name: str,
    *,
    config_path: Optional[str] = None,
    enable: bool = True,
    owner: str = DEFAULT_OWNER,
    repo: Optional[str] = None,
    branch: str = DEFAULT_BRANCH,
) -> dict[str, Any]:
    """安装 plugin config 到本地 tangyuanai.config.json，返回安装后的 feature dict。

    - 优先用已安装代码包内置 config（离线）
    - 否则从中央仓库下载 <plugin_name>.json
    """
    new_feat: Optional[dict[str, Any]] = None

    builtin = _builtin_configs_for(plugin_name)
    if builtin:
        new_feat = builtin[0]

    if new_feat is None:
        resolved_repo = _repo_for(plugin_name, repo)
        new_feat = await fetch_plugin_config(
            plugin_name, owner=owner, repo=resolved_repo, branch=branch,
        )

    if enable and "enabled" not in new_feat:
        new_feat["enabled"] = True

    config = load_config(config_path)
    config = merge_feature(config, new_feat)
    save_config(config, config_path)

    src = "插件包内置" if builtin else f"https://github.com/{owner}/{_repo_for(plugin_name, repo)}/"
    logger.info(f"plugin 已安装并启用: {plugin_name}（来自 {src}）")
    return new_feat


def list_installed(config_path: Optional[str] = None) -> list[dict[str, Any]]:
    """列出本地 config 里所有 enabled features。"""
    config = load_config(config_path)
    return [f for f in config.get("features", []) if f.get("enabled")]


# ---------------------------------------------------------------------------
# v1.1.1+ 新格式入口：识别 OpenAI ChatGPT Plugin 1.0 / Anthropic Claude Code Plugin
# ---------------------------------------------------------------------------

async def fetch_external_plugin(target: str, *, schema_format: str = "openai_chat"):
    """v1.1.1+ 新增：从 HTTP URL（OpenAI 协议）或本地路径（Anthropic 协议）加载 plugin manifest。

    返回 ``PluginSpec``（含 manifest + skills + mcp_servers + openapi_tools + hooks）。
    """
    from .plugin import load_plugin as _load
    return _load(target, schema_format=schema_format)


def install_external_plugin(target: str, *, schema_format: str = "openai_chat"):
    """v1.1.1+ 同步便捷：``fetch_external_plugin`` 的 sync 版。"""
    import asyncio as _aio
    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return _aio.run(fetch_external_plugin(target, schema_format=schema_format))
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_aio.run, fetch_external_plugin(target, schema_format=schema_format)).result()
