# -*- coding: utf-8 -*-
"""tangyuanai.plugin.manifest —— 统一 Plugin Manifest 模型。

**两个外部协议同源：都是「JSON 文件」**：

- **OpenAI ChatGPT Plugin 1.0**：HTTP `/.well-known/ai-plugin.json`（HTTP fetcher 拿 JSON 内容）
- **Anthropic Claude Code Plugin**：本地 `.claude-plugin/plugin.json`（Local fetcher 读 JSON 文件）

`PluginManifest` 把两协议字段集合成一份 pydantic 模型；`detect_protocol()`
根据已填充字段自动识别（openai / anthropic / unknown）。

**核心原则**：tangyuanAI 是协议的**客户端**，不是协议**定义者**。tangyuanAI 不发明
"Plugin 1.0"，只识别这两个外部标准。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ProtocolKind = Literal["openai", "anthropic", "unknown"]


class PluginManifest(BaseModel):
    """tangyuanAI Plugin 1.0 manifest（兼容 OpenAI / Anthropic 双协议）。

    字段集覆盖两协议：必填字段按 `extra="allow"` 模式接收，调用方按需读。
    """

    model_config = ConfigDict(extra="allow")

    # --- OpenAI ChatGPT Plugin 1.0 字段（HTTP manifest） ---
    schema_version: Optional[str] = None        # "v1" / "v2.1" / ...
    name_for_model: Optional[str] = None
    name_for_human: Optional[str] = None
    description_for_model: Optional[str] = None
    description_for_human: Optional[str] = None
    auth: dict[str, Any] = Field(default_factory=dict)
    api: dict[str, Any] = Field(default_factory=dict)   # {type:"openapi", url:...}
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    legal_info_url: Optional[str] = None

    # --- Anthropic Claude Code Plugin 字段（本地 manifest） ---
    name: Optional[str] = None                    # kebab-case 标识符
    version: Optional[str] = None                 # semver
    description: Optional[str] = None
    author: Optional[str] = None
    homepage: Optional[str] = None
    repository: Optional[str] = None
    license: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    commands: Optional[str] = None               # 路径引用
    agents: Optional[str] = None
    skills_dir: Optional[str] = None             # skills 目录路径（相对 manifest root）
    hooks: dict[str, Any] = Field(default_factory=dict)   # event → script

    # --- 来源元数据（tangyuanAI 内部） ---
    source: Literal["openai", "anthropic", "unknown"] = "unknown"
    manifest_path: Optional[str] = None           # 实际拿到的 manifest 文件 / URL
    plugin_root: Optional[str] = None             # plugin 根目录（Anthropic 模式）

    # --- OpenAPI spec（OpenAI 模式懒加载） ---
    openapi_spec: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "name_for_model", mode="before")
    @classmethod
    def _strip_name(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) and v.strip() else v

    def detect_protocol(self) -> ProtocolKind:
        """根据已填充字段自动识别协议类型。"""
        # OpenAI ChatGPT Plugin 1.0：必填 schema_version + api + auth
        if self.schema_version and self.api:
            return "openai"
        # Anthropic Claude Code Plugin：必填 name + version（带 kebab-case）
        if self.name and self.version and "-" in self.name:
            return "anthropic"
        return "unknown"

    @property
    def display_name(self) -> str:
        """统一显示名：OpenAI 取 name_for_human；Anthropic 取 name。"""
        return self.name_for_human or self.name_for_model or self.name or "unknown"

    @property
    def display_description(self) -> str:
        """统一描述：OpenAI 取 description_for_model（喂 LLM 用）；Anthropic 取 description。"""
        if self.description_for_model:
            return self.description_for_model
        return self.description_for_human or self.description or ""


def parse_manifest(
    content: str,
    *,
    source: Literal["openai", "anthropic", "unknown"] = "unknown",
    manifest_path: Optional[str] = None,
    plugin_root: Optional[str] = None,
) -> PluginManifest:
    """从 JSON / YAML 字符串解析 manifest。

    自动识别 JSON / YAML（按起始字符判断）。
    """
    raw: Any
    text = content.strip()
    if text.startswith("{") or text.startswith("["):
        import json
        raw = json.loads(text)
    else:
        raw = yaml.safe_load(text) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Plugin manifest 必须是 JSON object（实际是 {type(raw).__name__}）")

    # 推断 protocol（如果 caller 没传）
    if source == "unknown":
        if "schema_version" in raw and "api" in raw:
            source = "openai"
        elif "name" in raw and "version" in raw:
            source = "anthropic"

    manifest = PluginManifest(**raw)
    manifest.source = source
    manifest.manifest_path = manifest_path
    manifest.plugin_root = plugin_root
    return manifest


__all__ = ["PluginManifest", "ProtocolKind", "parse_manifest"]
