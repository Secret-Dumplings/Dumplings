# -*- coding: utf-8 -*-
"""tangyuanai.plugin_loader —— 插件发现 / 加载 / 命名空间桥接。

职责：
- 通过 ``importlib.metadata`` 发现 ``tangyuanai.plugins`` entry point（不 import 插件）
- 按 name 或 PLUGIN_TYPE 惰性加载插件模块
- 把插件 API 模块树别名注册到核心命名空间（如 ``tangyuanAI.kb`` / ``tangyuanAI.imaging``），
  使 ``from tangyuanAI.kb.config import EmbedderConfig`` 这类深层导入也能工作
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from types import ModuleType
from typing import Any, Optional

from .plugin_api import (
    ENTRY_POINT_GROUP,
    PluginEntry,
    PluginError,
)

__all__ = [
    "discover_plugins",
    "plugin_installed",
    "plugin_available",
    "load_plugin",
    "load_plugin_by_type",
    "get_plugin_api",
    "get_plugin_api_by_type",
    "get_plugin_configs",
    "install_module_alias",
    "resolve_plugin_for_namespace",
]


# ---------------------------------------------------------------------------
# 发现（不 import 插件模块）
# ---------------------------------------------------------------------------


def discover_plugins() -> dict[str, PluginEntry]:
    """返回 ``{entry_point_name: PluginEntry}``（轻量，不导入插件代码）。"""
    from importlib import metadata

    eps = metadata.entry_points()
    try:
        group = eps.select(group=ENTRY_POINT_GROUP)
    except AttributeError:  # Python 3.10 之前 / 个别环境
        group = eps.get(ENTRY_POINT_GROUP, [])
    out: dict[str, PluginEntry] = {}
    for ep in group:
        out[ep.name] = PluginEntry(name=ep.name, module=ep.value, target=ep.value)
    return out


def plugin_installed(name: str) -> bool:
    """entry point 是否注册（不 import，无法确认依赖是否完整）。"""
    return name in discover_plugins()


def plugin_available(name: str) -> bool:
    """插件是否真的能导入（依赖完整才算可用）。"""
    try:
        load_plugin(name)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 新格式入口（v1.1.1+）：识别 OpenAI / Anthropic 外部 manifest
# ---------------------------------------------------------------------------

def load_external_plugin(target: str, *, schema_format: str = "openai_chat"):
    """v1.1.1+ 新增：按 target 自动识别 OpenAI / Anthropic plugin manifest 并加载。

    Args:
        target: HTTP URL（OpenAI ChatGPT Plugin 1.0）或本地路径（Anthropic Claude Code Plugin）。
        schema_format: OpenAPI → tool schema 转换的目标格式（`openai_chat` / `openai_responses` / `anthropic`）。

    Returns:
        ``PluginSpec``（含 manifest + skills + mcp_servers + openapi_tools + hooks）。

    Raises:
        PluginError: target 不是新格式 plugin，或加载失败。
    """
    from .plugin import FetcherError
    from .plugin import load_plugin as _new_load_plugin
    try:
        return _new_load_plugin(target, schema_format=schema_format)
    except FetcherError as e:
        raise PluginError(f"加载外部 plugin 失败（{target}）：{e}") from e
    except ValueError as e:
        raise PluginError(f"target 不是新格式 plugin（{target}）：{e}") from e


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


def load_plugin(name: str) -> ModuleType:
    """按 entry point 名导入插件模块（失败抛 PluginError）。"""
    entries = discover_plugins()
    entry = entries.get(name)
    if entry is None:
        raise PluginError(
            f"plugin {name!r} 未安装。安装方式：pip install 'tangyuanAI[all]'，"
            "或单独 pip install 对应插件包。"
        )
    try:
        return entry.load()
    except PluginError:
        raise
    except Exception as e:
        raise PluginError(f"plugin {name!r} 加载失败: {e}") from e


def load_plugin_by_type(plugin_type: str) -> Optional[ModuleType]:
    """按 PLUGIN_TYPE 找第一个可导入的插件（需要 import 插件读契约字段）。"""
    for name in sorted(discover_plugins()):
        try:
            mod = load_plugin(name)
        except PluginError:
            continue
        if getattr(mod, "PLUGIN_TYPE", None) == plugin_type:
            return mod
    return None


def get_plugin_api(name: str) -> ModuleType:
    """加载插件并返回公开 API 模块（调用插件的 get_api()）。"""
    mod = load_plugin(name)
    get_api = getattr(mod, "get_api", None)
    if callable(get_api):
        api = get_api()
        if api is not None:
            return api
    return mod


def get_plugin_api_by_type(plugin_type: str) -> Optional[ModuleType]:
    """按类型找插件 API 模块；没装/加载失败返回 None。"""
    mod = load_plugin_by_type(plugin_type)
    if mod is None:
        return None
    get_api = getattr(mod, "get_api", None)
    if callable(get_api):
        try:
            api = get_api()
        except Exception:
            return None
        if api is not None:
            return api
    return mod


def get_plugin_configs(name: str) -> list[dict[str, Any]]:
    """插件内置的 feature config 列表（plugin install 用）。"""
    mod = load_plugin(name)
    return list(getattr(mod, "PLUGIN_CONFIGS", []) or [])


# ---------------------------------------------------------------------------
# 命名空间桥接
# ---------------------------------------------------------------------------


class _AliasMetaFinder(importlib.abc.MetaPathFinder):
    """把 ``target.<sub>`` 的惰性导入转发到 ``source.<sub>`` 并注册别名。

    例如 target="tangyuanAI.kb"、source="tangyuanAI_rag_plus"：
    ``from tangyuanAI.kb.embedder_openai import X`` → 实际导入
    ``tangyuanAI_rag_plus.embedder_openai``，并让 sys.modules 里两个名字都指向同一模块。
    """

    def __init__(self, target: str, source: str):
        self.target = target
        self.source = source

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.target:
            return None
        if not fullname.startswith(self.target + "."):
            return None
        src_fullname = self.source + fullname[len(self.target):]
        try:
            src_mod = importlib.import_module(src_fullname)
        except ImportError:
            return None
        # 已加载：后续 import 直接命中 sys.modules
        sys.modules[fullname] = src_mod
        return importlib.util.spec_from_loader(fullname, _AlreadyLoadedLoader(src_mod))


class _AlreadyLoadedLoader(importlib.abc.Loader):
    """spec 占位 loader：模块已经加载过，不需要执行。"""

    def __init__(self, module: ModuleType):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):
        pass


def install_module_alias(target: str, source_module: ModuleType) -> None:
    """把 ``source_module`` 的模块树别名注册到 ``target`` 命名空间。

    - 立即把已导入的子模块写入 ``sys.modules[target.<sub>]``
    - 安装 meta path finder，后续惰性导入 ``target.<sub>`` 也会转发到 source
    """
    src_name = source_module.__name__
    sys.modules[target] = source_module
    prefix = src_name + "."
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith(prefix):
            sys.modules[target + mod_name[len(src_name):]] = mod
    if not any(
        isinstance(f, _AliasMetaFinder) and f.target == target for f in sys.meta_path
    ):
        sys.meta_path.insert(0, _AliasMetaFinder(target, src_name))


def resolve_plugin_for_namespace(plugin_type: str) -> Optional[ModuleType]:
    """给核心桥接包用：按类型解析插件 API 模块，没装/失败返回 None。"""
    return get_plugin_api_by_type(plugin_type)
