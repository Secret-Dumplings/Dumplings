# -*- coding: utf-8 -*-
"""tangyuanai.plugin_api —— 插件契约（接口文档的代码形态）。

插件 = 一个独立的 pip 包，通过 entry point 组 ``tangyuanai.plugins`` 注册。
核心框架不捆绑任何实现，只按本契约发现、加载插件，并把插件 API 桥接到
``tangyuanAI.kb`` / ``tangyuanAI.imaging`` 等命名空间。

插件模块（entry point 指向的模块）必须暴露的字段/函数见
:class:`PluginModule`；第三方实现时按 ``docs/plugin-dev.md`` 开发即可。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ENTRY_POINT_GROUP",
    "PLUGIN_TYPE_KNOWLEDGE_BASE",
    "PLUGIN_TYPE_IMAGE",
    "PluginModule",
    "PluginEntry",
    "PluginError",
]

#: entry point 组名：插件包在 pyproject.toml 里注册
#: ``[project.entry-points."tangyuanai.plugins"]``
ENTRY_POINT_GROUP = "tangyuanai.plugins"

#: 框架认识的插件类型：knowledge_base（RAG 插件桥接到 tangyuanAI.kb）
PLUGIN_TYPE_KNOWLEDGE_BASE = "knowledge_base"

#: 框架认识的插件类型：image_generation（图片插件桥接到 tangyuanAI.imaging）
PLUGIN_TYPE_IMAGE = "image_generation"


@runtime_checkable
class PluginModule(Protocol):
    """插件模块契约（entry point 指向的模块）。

    必填：
    - ``PLUGIN_NAME``: 插件安装名（如 ``"rag"`` / ``"image"``）
    - ``PLUGIN_TYPE``: 插件类型（``knowledge_base`` / ``image_generation`` 或自定义）
    - ``PLUGIN_TITLE``: 展示名
    - ``PLUGIN_DESCRIPTION``: 一句话说明
    - ``PLUGIN_CONFIGS``: 该插件内置的 feature config 列表（与 ``tangyuanai.config.json`` 的
      feature schema 一致；``tangyuanai plugin install`` 可直接使用）

    可选（v1.1.1+）：
    - ``MANIFEST_PATH``: 指向外部 plugin manifest 路径（识别 OpenAI / Anthropic 标准）
    - ``get_api()``: 返回提供公开 API 的模块（默认返回插件模块自身）
    - ``add_cli_subparsers(subparsers)``: 注册 CLI 子命令
    - ``check()``: 环境自检，返回 (ok: bool, message: str)
    """
    PLUGIN_NAME: str
    PLUGIN_TYPE: str
    PLUGIN_TITLE: str
    PLUGIN_DESCRIPTION: str
    PLUGIN_CONFIGS: list[dict[str, Any]]

    def get_api(self) -> ModuleType:
        """返回插件公开 API 模块。"""
        ...

    def add_cli_subparsers(self, subparsers) -> None:
        """往 argparse 的 subparsers 里注册子命令。"""
        ...

    def check(self) -> tuple[bool, str]:
        """环境自检。"""
        ...


@dataclass(frozen=True)
class PluginEntry:
    """一次 entry point 注册（发现结果，不 import 插件模块）。"""

    name: str            # entry point 名
    module: str          # entry point value（模块路径）
    target: str          # 插件模块全名（同 module，保留给 CLI 提示）

    def load(self) -> ModuleType:
        """导入插件模块（重依赖首次加载较慢）。"""
        import importlib
        return importlib.import_module(self.module)


class PluginError(RuntimeError):
    """插件相关错误（未安装 / 加载失败 / 契约不符合）。"""
