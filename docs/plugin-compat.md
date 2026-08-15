---
slug: plugin-compat
title: 兼容外部 Plugin 协议
order: 9
icon: EXTENSION_OUTLINED
---

# Plugin 协议兼容（v1.1.1+）

tangyuanAI 的 plugin 体系是**协议的客户端**，**不发明新协议**。v1.1.1+ 同时识别两个外部标准：

- **OpenAI ChatGPT Plugin 1.0**：HTTP `/.well-known/ai-plugin.json` + OpenAPI 3.0 spec
- **Anthropic Claude Code Plugin**：本地 `.claude-plugin/plugin.json` + `skills/` + `.mcp.json` + `hooks/`

**核心原则**：两种协议都**降级到「JSON 文件解析」**——OpenAI 走 HTTP 拿 JSON 内容、Anthropic 走本地读 JSON 内容，**拿到 JSON 内容后路径一样**。

## 快速对比

| 维度 | OpenAI ChatGPT Plugin 1.0 | Anthropic Claude Code Plugin |
|---|---|---|
| manifest 位置 | `https://<host>/.well-known/ai-plugin.json` | `<plugin>/.claude-plugin/plugin.json` |
| sub-components | OpenAPI 3.0 spec（tools） | `skills/`（SKILL.md）+ `.mcp.json` + `hooks/` |
| 鉴权 | `auth.type`: `none` / `service_http` / `oauth` | hooks / MCP 自带 |
| 加载入口 | `tangyuanai plugin load <url>` | `tangyuanai plugin load <dir>` |

## 用法

### 加载本地 Anthropic plugin

```bash
tangyuanai plugin load ./my-plugin
```

plugin 目录结构：

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # 必需 manifest
├── skills/                  # 可选：Claude Agent Skills（SKILL.md）
│   └── summarize/
│       └── SKILL.md
├── hooks/                   # 可选：事件 hooks
└── .mcp.json                # 可选：MCP server 配置
```

### 加载 HTTP OpenAI plugin

```bash
tangyuanai plugin load https://weather.example.com
```

OpenAI plugin 主机需提供：

- `/.well-known/ai-plugin.json`（manifest）
- `api.url` 指向 OpenAPI 3.0 spec

### Python API

```python
from tangyuanAI import load_external_plugin

# 加载本地 Anthropic plugin
spec = load_external_plugin("./my-plugin")
print(spec.manifest.name, spec.manifest.version)
print("skills:", [s.name for s in spec.skills])
print("mcp_servers:", [len(spec.mcp_servers)])

# 加载 HTTP OpenAI plugin
spec = load_external_plugin("https://example.com")
print(spec.manifest.name_for_model)
print("openapi_tools:", [t["function"]["name"] for t in spec.openapi_tools])
```

## Manifest 字段映射

`PluginManifest` 把两协议字段集合成一份 pydantic 模型：

| 通用字段 | OpenAI | Anthropic |
|---|---|---|
| `name` | `name_for_human` / `name_for_model` | `name`（kebab-case） |
| `description` | `description_for_model` / `description_for_human` | `description` |
| `version` | `version`（可选） | `version`（必填，semver） |
| `auth` | `auth: {type, ...}` | n/a |
| `api` | `api: {type: "openapi", url}` | n/a |
| `skills_dir` | n/a | `skills_dir`（相对 plugin root） |
| `hooks` | n/a | `hooks: {event: script}` |
| `mcp_config_path` | n/a | `.mcp.json`（自动读） |
| `source`（自动） | `"openai"` | `"anthropic"` |

`detect_protocol()` 根据已填充字段自动识别（不依赖 `source`）。

## 旧 plugin 格式（向后兼容）

旧 `tangyuanai.plugins` entry point（5 必填字段：`PLUGIN_NAME/TYPE/TITLE/DESCRIPTION/CONFIGS`）+ 中央仓库 `<name>.json` feature config 仍可用，**计划 v1.3.0 删除**：

```bash
# 旧（仍兼容）：从中央仓库装 feature config
tangyuanai plugin install image_generation

# 新（推荐）：识别外部 plugin manifest
tangyuanai plugin load ./my-plugin
tangyuanai plugin load https://example.com
```

## OpenAPI 支持范围（v1.1.1）

`plugin/openapi.py::openapi_to_tools` 当前支持：

- `openapi: 3.0.x` spec
- `operationId` → tool name（规范化到 `^[a-zA-Z0-9_-]{1,64}$`）
- `summary` / `description` → tool description
- `requestBody.content."application/json".schema` + `parameters[]` → JSON Schema parameters
- 输出 schema_format：`openai_chat` / `openai_responses` / `anthropic`

**暂不支持**：`oneOf` / `anyOf` / `allOf` / `$ref`（抛清晰错误并提示）。复杂 spec 请报告 issue + 提供样例。