# -*- coding: utf-8 -*-
"""tangyuanai.plugin.loader —— 统一插件加载入口。

按 target 自动分派到 fetcher：

- `http(s)://...` 或含 `/.well-known/ai-plugin.json` → HTTPFetcher（OpenAI 协议）
- 本地路径（`.claude-plugin/plugin.json` 存在）→ LocalFetcher（Anthropic 协议）
- 中央仓库 name（向后兼容）→ GitHubSource
- entry point 名 → 旧 entry point（向后兼容；v1.3.0 删除）

**sub-component 加载复用既有模块**：skills → `skill.py`，mcp → `mcp_bridge.py`，hooks → 新建。
OpenAPI tools → `openapi.openapi_to_tools`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tangyuanAI.logging_config import get_logger

from .fetcher import HTTPFetcher, LocalFetcher
from .manifest import PluginManifest

_logger = get_logger("plugin.loader")

__all__ = ["PluginSpec", "load_plugin", "can_handle"]


@dataclass
class PluginSpec:
    """加载后的插件完整 spec：manifest + sub-components。"""

    manifest: PluginManifest
    skills: list[Any] = field(default_factory=list)         # 复用 skill.Skill 实例
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)  # MCP server config dict
    openapi_tools: list[dict[str, Any]] = field(default_factory=list)  # tool schema（按 schema_format）
    hooks: list[Any] = field(default_factory=list)           # 客户端 hook 句柄（v1.1.1 占位）

    @property
    def source(self) -> str:
        return self.manifest.source


# 启发式匹配：什么样的 target 走哪个 fetcher
_HTTP_RE = re.compile(r"^https?://", re.I)
_ANTHROPIC_PLUGIN_INDICATOR = ".claude-plugin"   # path 含这个 → Anthropic


def can_handle(target: str) -> bool:
    """target 是否能被新 plugin loader 识别。"""
    if _HTTP_RE.match(target):
        return True
    p = Path(target)
    if p.exists():
        return True
    return False


def _detect_fetcher(target: str):
    """按 target 形态选 fetcher。"""
    if _HTTP_RE.match(target):
        return HTTPFetcher(target)
    p = Path(target).expanduser()
    if p.exists():
        # 优先看是不是 Anthropic Claude Code plugin（.claude-plugin/plugin.json）
        if (p.is_dir() and (p / ".claude-plugin" / "plugin.json").exists()) or (
            p.is_file() and p.name == "plugin.json" and ".claude-plugin" in str(p)
        ):
            return LocalFetcher(str(p))
    # 不匹配新格式 → 抛 FetcherError（caller 决定 fallback 到旧 entry point）
    raise ValueError(f"target 不是新格式 plugin：{target}")


def load_plugin(
    target: str,
    *,
    schema_format: str = "openai_chat",
) -> PluginSpec:
    """统一加载入口。返回 PluginSpec（manifest + skills + mcp + openapi_tools + hooks）。"""
    fetcher = _detect_fetcher(target)
    manifest = fetcher.fetch()
    spec = PluginSpec(manifest=manifest)
    spec.openapi_tools = _load_openapi_tools(manifest, schema_format=schema_format)
    spec.skills = _load_skills(manifest)
    spec.mcp_servers = _load_mcp(manifest)
    spec.hooks = _load_hooks(manifest)
    return spec


def _load_openapi_tools(manifest: PluginManifest, *, schema_format: str) -> list[dict[str, Any]]:
    """OpenAI 模式：从 manifest.openapi_spec 转换。"""
    if manifest.source != "openai" or not manifest.openapi_spec:
        return []
    try:
        from .openapi import openapi_to_tools
        return openapi_to_tools(manifest.openapi_spec, schema_format=schema_format)  # type: ignore[arg-type]
    except NotImplementedError as e:
        _logger.warning(f"OpenAPI spec 含未支持结构（{e}）；跳过 tool 转换")
        return []
    except Exception as e:
        _logger.error(f"OpenAPI 转换失败：{e}")
        return []


def _load_skills(manifest: PluginManifest) -> list[Any]:
    """Anthropic 模式：从 skills_dir 目录扫 SKILL.md，复用 skill.py 解析。"""
    if manifest.source != "anthropic" or not manifest.skills_dir:
        return []
    if not manifest.plugin_root:
        return []
    skills_root = Path(manifest.plugin_root) / manifest.skills_dir
    if not skills_root.is_dir():
        return []

    from tangyuanAI.skill import Skill
    out: list[Skill] = []
    for skill_dir in sorted(skills_root.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            try:
                out.append(Skill(str(skill_dir), auto_register=False))
            except Exception as e:
                _logger.warning(f"加载 skill {skill_dir} 失败：{e}")
    return out


def _load_mcp(manifest: PluginManifest) -> list[dict[str, Any]]:
    """Anthropic 模式：读 .mcp.json，复用 mcp_bridge.py 客户端初始化逻辑（不立即启动）。"""
    if manifest.source != "anthropic" or not manifest.plugin_root:
        return []
    mcp_path = Path(manifest.plugin_root) / ".mcp.json"
    if not mcp_path.exists():
        return []
    try:
        import json
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        # mcpServers 是 Anthropic Claude Code 标准字段
        servers = data.get("mcpServers") or data.get("servers") or {}
        return list(servers.values()) if isinstance(servers, dict) else []
    except Exception as e:
        _logger.warning(f"读 .mcp.json 失败：{e}")
        return []


def _load_hooks(manifest: PluginManifest) -> list[Any]:
    """Anthropic 模式：从 manifest.hooks 字段读 hook 配置。v1.1.1 占位。"""
    if not manifest.hooks:
        return []
    _logger.debug(
        f"plugin {manifest.display_name} 含 {len(manifest.hooks)} 个 hook 配置；v1.1.1 仅记录不执行"
    )
    return list(manifest.hooks.items())
