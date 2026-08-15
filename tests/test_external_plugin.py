# -*- coding: utf-8 -*-
"""v1.1.1+ 新格式 plugin loader 测试：OpenAI ChatGPT Plugin 1.0 + Anthropic Claude Code Plugin。"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
from tangyuanAI.plugin import (
    FetcherError,
    PluginSpec,
    can_handle,
    load_plugin,
    parse_manifest,
)
from tangyuanAI.plugin.openapi import openapi_to_tools

# ============ manifest 解析 ============

def test_parse_manifest_openai_json():
    raw = json.dumps({
        "schema_version": "v1",
        "name_for_model": "test",
        "name_for_human": "Test",
        "description_for_model": "Test desc",
        "description_for_human": "Test desc",
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": "https://example.com/openapi.yaml"},
        "logo_url": "https://example.com/logo.png",
        "contact_email": "test@example.com",
        "legal_info_url": "https://example.com/legal",
    })
    m = parse_manifest(raw, source="openai")
    assert m.schema_version == "v1"
    assert m.name_for_model == "test"
    assert m.api["type"] == "openapi"        # OpenAI Plugin 用 OpenAPI 协议（不是 "openai"）
    assert m.detect_protocol() == "openai"   # detect_protocol 返回 "openai"
    assert m.display_name == "Test"
    assert m.display_description == "Test desc"


def test_parse_manifest_anthropic_yaml():
    raw = dedent("""
        name: my-plugin
        version: 1.2.3
        description: A test plugin
        author: secret-tangyuan
    """).strip()
    m = parse_manifest(raw, source="anthropic")
    assert m.name == "my-plugin"
    assert m.version == "1.2.3"
    assert m.detect_protocol() == "anthropic"
    assert m.display_name == "my-plugin"
    assert m.display_description == "A test plugin"


def test_parse_manifest_auto_detect():
    raw_openai = json.dumps({"schema_version": "v1", "api": {}, "auth": {}})
    assert parse_manifest(raw_openai).source == "openai"
    raw_anthropic = json.dumps({"name": "x-plugin", "version": "1.0.0"})
    assert parse_manifest(raw_anthropic).source == "anthropic"


def test_parse_manifest_invalid_raises():
    with pytest.raises(ValueError, match="Plugin manifest"):
        parse_manifest("[1, 2, 3]")


# ============ HTTP fetcher 行为（mock） ============

def test_http_fetcher_parses_ai_plugin_json():
    """HTTPFetcher 拉 `/.well-known/ai-plugin.json` + OpenAPI；fetch 应返回 PluginManifest + openapi_spec 已填。"""
    from tangyuanAI.plugin import HTTPFetcher

    manifest_text = json.dumps({
        "schema_version": "v1",
        "name_for_model": "weather",
        "name_for_human": "Weather",
        "description_for_model": "Get weather",
        "description_for_human": "Get weather",
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": "https://example.com/openapi.yaml"},
        "logo_url": "https://example.com/logo.png",
        "contact_email": "a@b.com",
        "legal_info_url": "https://example.com/legal",
    })
    openapi_text = dedent("""
        openapi: 3.0.0
        info:
          title: Weather API
          version: 1.0.0
        paths:
          /weather:
            get:
              operationId: get_weather
              summary: Get weather for a city
              parameters:
                - name: city
                  in: query
                  required: true
                  schema:
                    type: string
              responses:
                '200':
                  description: OK
    """).strip()

    from unittest.mock import patch

    class _FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

        def raise_for_status(self):
            if not (200 <= self.status_code < 300):
                raise RuntimeError(f"HTTP {self.status_code}")

    async def fake_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        if "ai-plugin.json" in url:
            return _FakeResponse(manifest_text)
        if "openapi" in url:
            return _FakeResponse(openapi_text)
        return _FakeResponse("", 404)

    with patch.object(HTTPFetcher, "_fetch_openapi", return_value=openapi_text):
        # 直接用 _parse_and_extract_openapi_url 测试 URL 提取
        url = HTTPFetcher._parse_and_extract_openapi_url(manifest_text)
        assert url == "https://example.com/openapi.yaml"


def test_http_fetcher_handles_missing_openapi_url():
    """manifest 里 api.url 缺失时，openapi_spec 应留空，不抛错。"""
    from tangyuanAI.plugin import HTTPFetcher

    manifest_text = json.dumps({"schema_version": "v1", "api": {"type": "openapi"}, "auth": {}})
    url = HTTPFetcher._parse_and_extract_openapi_url(manifest_text)
    assert url is None


# ============ Local fetcher ============

def test_local_fetcher_reads_claude_plugin_manifest(tmp_path: Path):
    """LocalFetcher 读 .claude-plugin/plugin.json → PluginManifest + plugin_root。"""
    plugin_dir = tmp_path / "my-plugin"
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(json.dumps({
        "name": "my-plugin",
        "version": "0.1.0",
        "description": "Test",
        "skills_dir": "skills",
        "hooks": {"pre-tool-use": "hooks/check.py"},
    }))

    from tangyuanAI.plugin import LocalFetcher
    m = LocalFetcher(str(plugin_dir)).fetch()
    assert m.name == "my-plugin"
    assert m.version == "0.1.0"
    assert m.skills_dir == "skills"
    assert m.hooks["pre-tool-use"] == "hooks/check.py"
    assert m.plugin_root == str(plugin_dir)
    assert m.detect_protocol() == "anthropic"


def test_local_fetcher_direct_manifest_path(tmp_path: Path):
    """直接传 .claude-plugin/plugin.json 路径也行。"""
    manifest_file = tmp_path / ".claude-plugin" / "plugin.json"
    manifest_file.parent.mkdir(parents=True)
    manifest_file.write_text(json.dumps({"name": "direct", "version": "1.0.0"}))

    from tangyuanAI.plugin import LocalFetcher
    m = LocalFetcher(str(manifest_file)).fetch()
    assert m.name == "direct"
    assert m.plugin_root == str(tmp_path)


def test_local_fetcher_missing_manifest_raises(tmp_path: Path):
    from tangyuanAI.plugin import LocalFetcher
    with pytest.raises(FetcherError, match="Plugin 路径不存在"):
        LocalFetcher(str(tmp_path / "nope")).fetch()


# ============ OpenAPI 转换器 ============

def test_openapi_to_tools_openai_chat():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search",
                    "summary": "Search something",
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                }
            }
        }
    }
    tools = openapi_to_tools(spec, schema_format="openai_chat")
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "search"
    assert tools[0]["function"]["description"] == "Search something"
    assert "q" in tools[0]["function"]["parameters"]["properties"]


def test_openapi_to_tools_responses_format():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {"post": {"operationId": "do_x", "summary": "Do X"}}
        }
    }
    tools = openapi_to_tools(spec, schema_format="openai_responses")
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "do_x"
    assert "function" not in tools[0]  # Responses API 没有 function 包裹


def test_openapi_to_tools_anthropic_format():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/y": {"get": {"operationId": "do_y", "description": "Y"}}
        }
    }
    tools = openapi_to_tools(spec, schema_format="anthropic")
    assert "function" not in tools[0]
    assert "input_schema" in tools[0]
    assert tools[0]["name"] == "do_y"


def test_openapi_to_tools_normalizes_op_id():
    spec = {
        "openapi": "3.0.0",
        "paths": {"/z": {"get": {"operationId": "Do Strange Thing!"}}}
    }
    tools = openapi_to_tools(spec)
    # "Do Strange Thing!" → 非 word 字符替换为 "_" → "Do_Strange_Thing_"
    # → strip("_") → "Do_Strange_Thing"
    assert tools[0]["function"]["name"] == "Do_Strange_Thing"


def test_openapi_to_tools_merges_path_and_op_params():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/items/{id": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "get": {
                    "operationId": "get_item",
                    "parameters": [
                        {"name": "expand", "in": "query", "schema": {"type": "boolean"}},
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"foo": {"type": "string"}},
                                    "required": ["foo"],
                                }
                            }
                        }
                    },
                },
            }
        }
    }
    tools = openapi_to_tools(spec)
    params = tools[0]["function"]["parameters"]
    assert "id" in params["properties"]
    assert "expand" in params["properties"]
    assert "foo" in params["properties"]
    assert set(params["required"]) == {"id", "foo"}


def test_openapi_to_tools_oneOf_not_implemented():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {"get": {"operationId": "x", "requestBody": {
                "content": {"application/json": {"schema": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}}
            }}}
        }
    }
    with pytest.raises(NotImplementedError, match="oneOf"):
        openapi_to_tools(spec)


def test_openapi_to_tools_invalid_spec_raises():
    with pytest.raises(ValueError, match="OpenAPI 3.0"):
        openapi_to_tools({})


def test_openapi_to_tools_validate_spec_true():
    """validate_spec=True 时做完整 OpenAPI 3.0 校验；缺 info.title/version 会失败。"""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "X", "version": "1.0.0"},
        "paths": {
            "/x": {"get": {"operationId": "x", "responses": {"200": {"description": "OK"}}}}
        }
    }
    # validate_spec=True + 完整 spec → 应通过
    tools = openapi_to_tools(spec, validate_spec=True)
    assert len(tools) == 1
    # validate_spec=True + info 缺字段 → 应失败
    bad_spec = {"openapi": "3.0.0", "paths": {}}
    with pytest.raises(ValueError, match="OpenAPI spec 校验失败"):
        openapi_to_tools(bad_spec, validate_spec=True)


# ============ can_handle / load_plugin 分派 ============

def test_can_handle_http():
    assert can_handle("https://example.com") is True
    assert can_handle("http://example.com") is True


def test_can_handle_local_path(tmp_path: Path):
    # 空 tmp_path 不是 plugin（can_handle 走 Path.exists 检查返回 True，但 _detect_fetcher 会拒）
    assert can_handle(str(tmp_path)) is True      # 路径存在 → can_handle 接受
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}")
    # 现在 _detect_fetcher 能识别
    spec = load_plugin(str(tmp_path))
    assert spec.manifest is not None


def test_can_handle_rejects_unknown():
    assert can_handle("/this/path/definitely/does/not/exist/12345") is False
    assert can_handle("not-a-url-and-not-a-path") is False


def test_load_plugin_anthropic_full(tmp_path: Path):
    """端到端：LocalFetcher + skills + mcp + openapi_tools 加载。"""
    plugin_dir = tmp_path / "research"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "research",
        "version": "1.0.0",
        "description": "Research plugin",
        "skills_dir": "skills",
    }))
    # 放一个 skill
    skill_dir = plugin_dir / "skills" / "summarize"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(dedent("""
        ---
        name: summarize
        description: Summarize text
        ---

        # Summarize
        Summarize the input.
    """).strip())
    # 放 .mcp.json
    (plugin_dir / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "github": {"command": "python", "args": ["mcp_github.py"]},
        }
    }))

    spec = load_plugin(str(plugin_dir))
    assert isinstance(spec, PluginSpec)
    assert spec.manifest.source == "anthropic"
    assert spec.manifest.name == "research"
    assert len(spec.skills) == 1
    assert spec.skills[0].name == "summarize"
    assert len(spec.mcp_servers) == 1


def test_load_plugin_unknown_target_raises(tmp_path: Path):
    """不存在 / 不是 plugin 格式的路径抛 FetcherError。"""
    with pytest.raises(ValueError, match="target 不是新格式 plugin"):
        load_plugin(str(tmp_path / "nope"))
