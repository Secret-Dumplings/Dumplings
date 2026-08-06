# -*- coding: utf-8 -*-
"""tangyuanai.plugin_store —— 从中央 config 仓库下载 + 合并 plugin config。

中央仓库（v1 真实地址）：
    https://github.com/secret-tangyuan/tangyuanAI_image_plus
    → raw URL 模板：
        https://raw.githubusercontent.com/secret-tangyuan/tangyuanAI_image_plus/main/{plugin_name}.json

下载 → 解析 → merge 到本地 tangyuanai.config.json 的 features 列表（同 name 替换，新 append）。
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import load_config, merge_feature, save_config
from .logging_config import logger

__all__ = ["install_plugin", "list_installed", "fetch_plugin_config"]


# 中央仓库配置（v1：真实地址；后续可改 owner/repo/branch）
DEFAULT_OWNER = "secret-tangyuan"
DEFAULT_REPO = "tangyuanAI_image_plus"
DEFAULT_BRANCH = "main"

# raw URL 模板（GitHub raw content）
_CENTRAL_REPO_URL = (
    "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{plugin_name}.json"
)


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


async def install_plugin(
    plugin_name: str,
    *,
    config_path: Optional[str] = None,
    enable: bool = True,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
) -> dict[str, Any]:
    """下载 plugin config → merge 到本地 tangyuanai.config.json → 启用。

    Returns: 安装后的 feature dict。
    """
    new_feat = await fetch_plugin_config(
        plugin_name, owner=owner, repo=repo, branch=branch,
    )
    if enable and "enabled" not in new_feat:
        new_feat["enabled"] = True

    config = load_config(config_path)
    config = merge_feature(config, new_feat)
    save_config(config, config_path)

    logger.info(
        f"plugin 已安装并启用: {plugin_name}（来自 https://github.com/{owner}/{repo}/）"
    )
    return new_feat


def list_installed(config_path: Optional[str] = None) -> list[dict[str, Any]]:
    """列出本地 config 里所有 enabled features。"""
    config = load_config(config_path)
    return [f for f in config.get("features", []) if f.get("enabled")]
