# -*- coding: utf-8 -*-
"""
plugin_store 测试（tests/test_plugin_store.py）
=============================================
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from tangyuanAI.plugin_store import (
    install_plugin,
    list_installed,
    merge_feature,
)


class TestMergeFeature:
    def test_append(self):
        out = merge_feature({"features": [{"name": "a"}]}, {"name": "b"})
        assert [f["name"] for f in out["features"]] == ["a", "b"]

    def test_replace(self):
        out = merge_feature({"features": [{"name": "a", "old": 1}]}, {"name": "a", "new": 2})
        assert len(out["features"]) == 1
        assert out["features"][0]["new"] == 2

    def test_no_features(self):
        out = merge_feature({}, {"name": "a"})
        assert out["features"] == [{"name": "a"}]


class TestInstallPlugin:
    @pytest.mark.asyncio
    async def test_install_writes_config(self, tmp_path):
        """mock fetch → 验证写回 config + 启用。"""
        fetched = {
            "name": "image_generation",
            "type": "image_generation",
            "config": {"provider": "siliconflow"},
        }
        config_file = tmp_path / "tangyuanai.config.json"

        with patch("tangyuanAI.plugin_store.fetch_plugin_config",
                   new=AsyncMock(return_value=fetched)):
            result = await install_plugin("image_generation", config_path=str(config_file))

        assert result["enabled"] is True  # 自动启用
        # 验证写回
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["features"][0]["name"] == "image_generation"
        assert saved["features"][0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_install_no_enable(self, tmp_path):
        fetched = {"name": "img", "type": "image_generation", "config": {}}
        config_file = tmp_path / "c.json"
        with patch("tangyuanAI.plugin_store.fetch_plugin_config",
                   new=AsyncMock(return_value=fetched)):
            await install_plugin("img", config_path=str(config_file), enable=False)
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert "enabled" not in saved["features"][0]

    @pytest.mark.asyncio
    async def test_install_preserves_existing(self, tmp_path):
        config_file = tmp_path / "c.json"
        config_file.write_text(json.dumps({"features": [{"name": "old"}]}), encoding="utf-8")
        fetched = {"name": "new", "type": "image_generation", "config": {}}
        with patch("tangyuanAI.plugin_store.fetch_plugin_config",
                   new=AsyncMock(return_value=fetched)):
            await install_plugin("new", config_path=str(config_file))
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert [f["name"] for f in saved["features"]] == ["old", "new"]


class TestListInstalled:
    def test_list(self, tmp_path):
        config_file = tmp_path / "c.json"
        config_file.write_text(json.dumps({
            "features": [
                {"name": "a", "enabled": True},
                {"name": "b", "enabled": False},
            ]
        }), encoding="utf-8")
        names = [f["name"] for f in list_installed(str(config_file))]
        assert names == ["a"]
