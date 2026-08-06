# -*- coding: utf-8 -*-
"""
config 模块单测（tests/test_config.py）
=====================================
"""
from __future__ import annotations

import json

from tangyuanAI import config as cfg_mod


def _write_config(tmp_path, data: dict) -> str:
    p = tmp_path / "tangyuanai.config.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


class TestLoadConfig:
    def test_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TANGYUAN_CONFIG", str(tmp_path / "nope.json"))
        assert cfg_mod.load_config() == {}

    def test_explicit_path(self, tmp_path):
        path = _write_config(tmp_path, {"features": []})
        assert cfg_mod.load_config(path) == {"features": []}

    def test_env_path(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, {"features": []})
        monkeypatch.setenv("TANGYUAN_CONFIG", path)
        assert cfg_mod.load_config() == {"features": []}

    def test_bad_json_warns_not_crash(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not-json{{", encoding="utf-8")
        assert cfg_mod.load_config(str(p)) == {}


class TestFindAndList:
    def _cfg(self):
        return {
            "features": [
                {"name": "img_a", "type": "image_generation", "enabled": True,
                 "config": {"provider": "siliconflow"}},
                {"name": "img_b", "type": "image_generation", "enabled": False,
                 "config": {"provider": "dashscope"}},
                {"name": "vid", "type": "video_generation", "enabled": True,
                 "config": {"provider": "x"}},
            ]
        }

    def test_find_feature(self):
        f = cfg_mod.find_feature(self._cfg(), "img_a")
        assert f is not None and f["config"]["provider"] == "siliconflow"

    def test_find_missing(self):
        assert cfg_mod.find_feature(self._cfg(), "nope") is None

    def test_get_enabled(self):
        enabled = cfg_mod.get_enabled_features(self._cfg())
        assert [f["name"] for f in enabled] == ["img_a", "vid"]

    def test_get_enabled_by_type(self):
        imgs = cfg_mod.get_enabled_features(self._cfg(), "image_generation")
        assert [f["name"] for f in imgs] == ["img_a"]

    def test_find_by_type(self):
        f = cfg_mod.find_feature_by_type(self._cfg(), "image_generation")
        assert f is not None and f["name"] == "img_a"


class TestMerge:
    def test_append_new(self):
        out = cfg_mod.merge_feature({"features": [{"name": "a"}]}, {"name": "b"})
        assert [f["name"] for f in out["features"]] == ["a", "b"]

    def test_replace_same_name(self):
        out = cfg_mod.merge_feature({"features": [{"name": "a"}]}, {"name": "a", "enabled": True})
        assert [f["name"] for f in out["features"]] == ["a"]
        assert out["features"][0]["enabled"] is True

    def test_preserve_other_keys(self):
        out = cfg_mod.merge_feature({"version": 1, "features": [{"name": "a"}]}, {"name": "b"})
        assert out["version"] == 1


class TestResolveUrlTemplate:
    def test_env_placeholder(self):
        out = cfg_mod.resolve_url_template(
            "https://${env:WS_ID}.example.com/api", {"WS_ID": "ws-1"}
        )
        assert out == "https://ws-1.example.com/api"

    def test_no_placeholder(self):
        assert cfg_mod.resolve_url_template("https://api.example.com", {}) == "https://api.example.com"


class TestSaveConfig:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "out.json"
        cfg_mod.save_config({"features": [{"name": "a"}]}, str(p))
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == {"features": [{"name": "a"}]}
