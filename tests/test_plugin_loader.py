# -*- coding: utf-8 -*-
"""plugin_loader / plugin_api 测试（不依赖任何插件包）。"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def fake_plugin_pkg():
    """在临时目录造一个插件模块树，注册进 sys.path 供别名测试。"""
    with tempfile.TemporaryDirectory() as d:
        pkg = Path(d) / "tangyuanAI_fake_plus"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "PUBLIC_API = 'fake'\nfrom . import sub\n", encoding="utf-8"
        )
        (pkg / "sub.py").write_text("VALUE = 42\n", encoding="utf-8")
        (pkg / "lazy.py").write_text("VALUE = 'lazy'\n", encoding="utf-8")
        sys.path.insert(0, d)
        try:
            yield pkg
        finally:
            sys.path.remove(d)
            for name in list(sys.modules):
                if name.startswith("tangyuanAI_fake_plus"):
                    del sys.modules[name]
            for name in list(sys.modules):
                if name.startswith("tangyuanAI_alias_target"):
                    del sys.modules[name]
            # 移除安装过的 meta finder
            sys.meta_path = [f for f in sys.meta_path
                             if not (hasattr(f, "target") and f.target == "tangyuanAI_alias_target")]


class TestDiscover:
    def test_discover_returns_dict(self):
        from tangyuanAI.plugin_loader import discover_plugins

        plugins = discover_plugins()
        assert isinstance(plugins, dict)


class TestAlias:
    def test_module_alias_identity(self, fake_plugin_pkg):
        from tangyuanAI.plugin_loader import install_module_alias

        src = importlib.import_module("tangyuanAI_fake_plus")
        install_module_alias("tangyuanAI_alias_target", src)

        target = importlib.import_module("tangyuanAI_alias_target")
        assert target is src
        assert target.PUBLIC_API == "fake"

    def test_deep_submodule_alias_identity(self, fake_plugin_pkg):
        from tangyuanAI.plugin_loader import install_module_alias

        src = importlib.import_module("tangyuanAI_fake_plus")
        install_module_alias("tangyuanAI_alias_target", src)

        # 已导入子模块：同一对象
        assert sys.modules["tangyuanAI_alias_target.sub"] is sys.modules["tangyuanAI_fake_plus.sub"]

    def test_lazy_submodule_forward(self, fake_plugin_pkg):
        """未导入过的子模块经 meta finder 转发，且仍是同一对象。"""
        from tangyuanAI.plugin_loader import install_module_alias

        src = importlib.import_module("tangyuanAI_fake_plus")
        install_module_alias("tangyuanAI_alias_target", src)
        assert "tangyuanAI_fake_plus.lazy" not in sys.modules

        mod = importlib.import_module("tangyuanAI_alias_target.lazy")
        assert mod.VALUE == "lazy"
        assert mod is sys.modules["tangyuanAI_fake_plus.lazy"]


class TestBridgeMissing:
    def test_kb_bridge_raises_helpful_error(self):
        """未装 RAG 插件时，tangyuanAI.kb 取 API 应给安装提示。"""
        import tangyuanAI.kb as kb
        from tangyuanAI import plugin_loader

        if plugin_loader.load_plugin_by_type("knowledge_base") is not None:
            pytest.skip("RAG 插件已安装，跳过")
        with pytest.raises(ImportError) as e:
            kb.register_kb
        assert "tangyuanAI[all]" in str(e.value) or "tangyuanai-rag-plus" in str(e.value)
