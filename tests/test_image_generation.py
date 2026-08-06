# -*- coding: utf-8 -*-
"""
图片生成测试（tests/test_image_generation.py）
=============================================

覆盖：
- render_template / resolve_json_path / resolve_url_template 工具
- HttpJsonImageProvider.generate（mock httpx）
- download_urls（mock httpx）
- ImageGenerator.generate 路由 / 未启用 / download 路径
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tangyuanAI.imaging import (
    HttpJsonImageProvider,
    ImageError,
    ImageGenerator,
    render_template,
    resolve_json_path,
    resolve_url_template,
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

class TestTools:
    def test_render_template_basic(self):
        t = {"model": "${model}", "prompt": "${prompt}", "n": 42}
        out = render_template(t, {"model": "m1", "prompt": "hi"})
        assert out == {"model": "m1", "prompt": "hi", "n": 42}

    def test_render_template_skip_none(self):
        t = {"a": "${a}", "b": "${b}"}
        out = render_template(t, {"a": 1, "b": None})
        assert out == {"a": 1}  # b 为 None → 剔除

    def test_render_template_nested(self):
        t = {"input": {"messages": [{"content": [{"text": "${prompt}"}]}]}}
        out = render_template(t, {"prompt": "hi"})
        assert out["input"]["messages"][0]["content"][0]["text"] == "hi"

    def test_render_template_list(self):
        t = ["${a}", "${b}", "static"]
        out = render_template(t, {"a": 1, "b": None})
        assert out == [1, None, "static"]  # 列表里不剔除 None（保留占位）

    def test_resolve_json_path(self):
        data = {"data": [{"url": "http://x"}, {"url": "http://y"}]}
        assert resolve_json_path(data, "data.0.url") == "http://x"
        assert resolve_json_path(data, "data.1.url") == "http://y"
        assert resolve_json_path(data, "data.2.url") is None
        assert resolve_json_path(data, "missing") is None

    def test_resolve_json_path_nested(self):
        data = {"output": {"choices": [{"message": {"content": [{"image": "u"}]}}]}}
        assert resolve_json_path(data, "output.choices.0.message.content.0.image") == "u"

    def test_resolve_url_template(self):
        out = resolve_url_template(
            "https://${env:WS}.example.com/api", {"WS": "ws-1"}
        )
        assert out == "https://ws-1.example.com/api"


# ---------------------------------------------------------------------------
# HttpJsonImageProvider（mock httpx）
# ---------------------------------------------------------------------------

class TestHttpJsonImageProvider:
    def _cfg(self, **over):
        cfg = {
            "provider": "siliconflow",
            "api_base": "https://api.siliconflow.cn/v1",
            "api_key_env": "TEST_IMG_KEY",
            "default_model": "Qwen/Qwen-Image-Edit-2509",
            "request_template": {
                "model": "${model}",
                "prompt": "${prompt}",
                "image_size": "${image_size}",
                "negative_prompt": "${negative_prompt}",
            },
            "request_static": {"stream": False},
            "response_image_url_path": "data.0.url",
        }
        cfg.update(over)
        return cfg

    @pytest.fixture
    def provider(self, monkeypatch):
        monkeypatch.setenv("TEST_IMG_KEY", "sk-test")
        p = HttpJsonImageProvider(name="siliconflow", feature_cfg=self._cfg())
        yield p
        import asyncio
        asyncio.run(p.close())

    @pytest.mark.asyncio
    async def test_generate_flat_body(self, provider):
        """mock _client.apost → 验证模板填充 + 请求头 + 响应 URL 抽取。"""
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "created": 123, "data": [{"url": "http://img/1.png"}]
        }
        provider._client = MagicMock()
        provider._client.apost = AsyncMock(return_value=fake_resp)

        urls = await provider.generate(prompt="a cat", image_size="1024x1024")

        assert urls == ["http://img/1.png"]
        # 验证请求体
        call = provider._client.apost.call_args
        body = call.kwargs["json"]
        assert body["model"] == "Qwen/Qwen-Image-Edit-2509"  # default_model
        assert body["prompt"] == "a cat"
        assert body["image_size"] == "1024x1024"
        assert body["stream"] is False  # static
        assert "negative_prompt" not in body  # None → 剔除
        # 验证请求头
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"

    @pytest.mark.asyncio
    async def test_generate_dashscope_nested(self, monkeypatch):
        """DashScope nested body：prompt → input.messages[0].content[0].text。"""
        monkeypatch.setenv("DASHSCOPE_KEY_TEST", "sk-dash")
        cfg = {
            "provider": "dashscope",
            "api_base": "https://${env:DS_WS}.maas.example.com/gen",
            "api_key_env": "DASHSCOPE_KEY_TEST",
            "default_model": "qwen-image-3.0-pro",
            "request_template": {
                "model": "${model}",
                "input": {"messages": [{"role": "user", "content": [{"text": "${prompt}"}]}]},
                "parameters": {"size": "${image_size}"},
            },
            "response_image_url_path": "output.choices.0.message.content.0.image",
        }
        monkeypatch.setenv("DS_WS", "ws-9")
        p = HttpJsonImageProvider(name="dashscope", feature_cfg=cfg)
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "output": {"choices": [{"message": {"content": [{"image": "http://img/d.png"}]}}]}
        }
        p._client = MagicMock()
        p._client.apost = AsyncMock(return_value=fake_resp)

        urls = await p.generate(prompt="人像", image_size="1024x1024")
        assert urls == ["http://img/d.png"]

        call = p._client.apost.call_args
        body = call.kwargs["json"]
        assert body["input"]["messages"][0]["content"][0]["text"] == "人像"
        assert body["parameters"]["size"] == "1024x1024"
        # URL template 已替换
        assert call.kwargs["json"]["model"] == "qwen-image-3.0-pro"
        await p.close()

    def test_missing_api_key_env(self, monkeypatch):
        monkeypatch.delenv("TEST_IMG_KEY", raising=False)
        with pytest.raises(ImageError, match="未设置"):
            HttpJsonImageProvider(name="x", feature_cfg=self._cfg())


# ---------------------------------------------------------------------------
# download_urls（mock httpx）
# ---------------------------------------------------------------------------

class TestDownload:
    @pytest.mark.asyncio
    async def test_download(self, tmp_path):
        from tangyuanAI.imaging.provider import download_urls

        fake_content = b"\x89PNG fake"
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.content = fake_content

        with patch("tangyuanAI.http_utils.AsyncHTTPClient") as MockHTTP:
            mock_client = MagicMock()
            mock_client.client.get = AsyncMock(return_value=fake_resp)
            mock_client.close = AsyncMock()
            MockHTTP.return_value = mock_client

            paths = await download_urls(["http://img/1.png"], str(tmp_path))

        assert len(paths) == 1
        import os
        assert os.path.isfile(paths[0])
        assert open(paths[0], "rb").read() == fake_content

    @pytest.mark.asyncio
    async def test_skip_existing(self, tmp_path):
        from tangyuanAI.imaging.provider import download_urls

        # 已存在 → 跳过下载
        existing = tmp_path / "already.png"
        existing.write_bytes(b"old")
        # 构造一个 url，其 hash 已知会命中 already 文件？—— 用已存在文件做幂等验证：
        # 直接给一个 url，写同名文件先
        import hashlib
        url = "http://img/same.png"
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".png"
        (tmp_path / name).write_bytes(b"cached")

        with patch("tangyuanAI.http_utils.AsyncHTTPClient") as MockHTTP:
            mock_client = MagicMock()
            mock_client.client.get = AsyncMock()  # 不应被调用
            mock_client.close = AsyncMock()
            MockHTTP.return_value = mock_client

            paths = await download_urls([url], str(tmp_path))

        assert paths == [str(tmp_path / name)]
        mock_client.client.get.assert_not_awaited()  # 跳过下载


# ---------------------------------------------------------------------------
# ImageGenerator（config 路由）
# ---------------------------------------------------------------------------

class TestImageGenerator:
    def _write_cfg(self, tmp_path, enabled=True):
        cfg = {
            "features": [{
                "name": "image_generation",
                "type": "image_generation",
                "enabled": enabled,
                "config": {
                    "provider": "siliconflow",
                    "api_base": "https://api.siliconflow.cn/v1",
                    "api_key_env": "TEST_IMG_KEY",
                    "default_model": "Qwen/Qwen-Image-Edit-2509",
                    "request_template": {"model": "${model}", "prompt": "${prompt}"},
                    "response_image_url_path": "data.0.url",
                },
            }]
        }
        p = tmp_path / "tangyuanai.config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        return str(p)

    @pytest.mark.asyncio
    async def test_generate_routes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_IMG_KEY", "sk")
        path = self._write_cfg(tmp_path)
        g = ImageGenerator(config_path=path)

        with patch.object(g, "_get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.generate = AsyncMock(return_value=["http://img/1"])
            mock_get.return_value = mock_provider

            urls = await g.generate("image_generation", prompt="hi", image_size="1024x1024")

        assert urls == ["http://img/1"]
        mock_provider.generate.assert_awaited_once()
        # model 从 config default_model 补
        assert mock_provider.generate.await_args.kwargs["model"] == "Qwen/Qwen-Image-Edit-2509"
        await g.close()

    @pytest.mark.asyncio
    async def test_disabled_feature(self, tmp_path):
        path = self._write_cfg(tmp_path, enabled=False)
        g = ImageGenerator(config_path=path)
        with pytest.raises(ImageError, match="未在 config 启用"):
            await g.generate("image_generation", prompt="hi")
        await g.close()

    @pytest.mark.asyncio
    async def test_download_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_IMG_KEY", "sk")
        path = self._write_cfg(tmp_path)
        g = ImageGenerator(config_path=path)

        with patch("tangyuanAI.imaging.generator.download_urls",
                   new=AsyncMock(return_value=["/tmp/x.png"])) as mock_dl:
            with patch.object(g, "_get_provider") as mock_get:
                mock_provider = MagicMock()
                mock_provider.generate = AsyncMock(return_value=["http://img/1"])
                mock_get.return_value = mock_provider
                paths = await g.generate("image_generation", prompt="hi", download=True)
        assert paths == ["/tmp/x.png"]
        mock_dl.assert_awaited_once()
        await g.close()
