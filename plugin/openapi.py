# -*- coding: utf-8 -*-
"""tangyuanai.plugin.openapi —— OpenAPI 3.0 spec → tool schema 转换器。

OpenAI ChatGPT Plugin 1.0 引用 OpenAPI spec 描述 tools；本模块按目标 schema_format
转换：

- `openai_chat`：OpenAI Chat Completions `tools[].function.{name,description,parameters}`
- `openai_responses`：OpenAI Responses API `tools[]{type:"function", name, description, parameters}`
- `anthropic`：Anthropic Messages `tools[]{name, description, input_schema}`

**支持的 OpenAPI 子集（v1.1.1）**：
- `operationId` → tool `name`（规范化到 `^[a-zA-Z0-9_-]{1,64}$`）
- `summary` / `description` → tool `description`
- `requestBody.content."application/json".schema` + `parameters[]` → JSON Schema parameters
- `oneOf / allOf / discriminator / $ref`：留 TODO（复杂 spec 抛清晰错误）

复杂 spec（oneOf/allOf 等）请报告 issue；本模块按需求增量支持。
"""
from __future__ import annotations

import re
from typing import Any, Literal

SchemaFormat = Literal["openai_chat", "openai_responses", "anthropic"]

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _normalize_op_id(op_id: str) -> str:
    """OpenAPI operationId → tool name（OpenAI 要求 ^[a-zA-Z0-9_-]{1,64}$）。"""
    s = _NAME_RE.sub("_", op_id).strip("_")
    return s[:64] or "tool"


def _resolve_schema_ref(spec: dict, ref: str) -> dict[str, Any]:
    """解析 `$ref: "#/components/schemas/Foo"` → spec["components"]["schemas"]["Foo"]。"""
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    cur: Any = spec
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return {}
    return cur if isinstance(cur, dict) else {}


def _resolve_schema(spec: dict, schema: dict[str, Any]) -> dict[str, Any]:
    """递归解 `$ref`；遇到 `oneOf/allOf` 抛 NotImplementedError。"""
    if not isinstance(schema, dict):
        return {"type": "string"}
    if "$ref" in schema:
        return _resolve_schema(spec, _resolve_schema_ref(spec, schema["$ref"]))
    if "oneOf" in schema or "anyOf" in schema or "allOf" in schema:
        raise NotImplementedError(
            "OpenAPI oneOf/anyOf/allOf 暂不支持（v1.1.1 TODO）；请报告 issue + 提供 spec 样例"
        )
    # 递归 properties / items
    out = dict(schema)
    if "properties" in out and isinstance(out["properties"], dict):
        out["properties"] = {
            k: _resolve_schema(spec, v) for k, v in out["properties"].items()
        }
    if "items" in out and isinstance(out["items"], dict):
        out["items"] = _resolve_schema(spec, out["items"])
    return out


def _operation_parameters(
    spec: dict,
    op: dict[str, Any],
    path_item: dict[str, Any],
) -> dict[str, Any]:
    """合并 OpenAPI path-level + operation-level parameters + requestBody schema。"""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for p in list(path_item.get("parameters", [])) + list(op.get("parameters", [])):
        schema = p.get("schema") or {"type": "string"}
        schema = _resolve_schema(spec, schema)
        properties[p["name"]] = {
            "type": schema.get("type", "string"),
            "description": p.get("description", ""),
        }
        if p.get("required", False):
            required.append(p["name"])

    rb = op.get("requestBody") or {}
    content = rb.get("content") or {}
    json_content = content.get("application/json") or {}
    body_schema = json_content.get("schema") or {}
    if body_schema:
        body_schema = _resolve_schema(spec, body_schema)
        for name, prop in (body_schema.get("properties") or {}).items():
            properties[name] = prop
        if "required" in body_schema and isinstance(body_schema["required"], list):
            required.extend(body_schema["required"])

    return {"type": "object", "properties": properties, "required": required}


def openapi_to_tools(
    spec: dict[str, Any],
    *,
    schema_format: SchemaFormat = "openai_chat",
    validate_spec: bool = False,
) -> list[dict[str, Any]]:
    """OpenAPI 3.0 spec → tools schema 列表。

    每个 path × method 产出一个 tool。

    Args:
        spec: OpenAPI 3.0+ 文档 dict
        schema_format: 输出格式（`openai_chat` / `openai_responses` / `anthropic`）
        validate_spec: 是否做完整 OpenAPI 3.0 合法性校验（默认 False，避免简单 spec 因缺
                      `info.title` / `info.version` 等 metadata 而 fail；生产环境可开）
    """
    if spec.get("openapi", "").startswith("3.0") is False and "openapi" not in spec:
        raise ValueError("不是 OpenAPI 3.0+ spec（顶层缺 openapi 字段）")

    if validate_spec:
        try:
            from openapi_spec_validator import validate
            validate(spec)
        except ImportError:
            pass
        except Exception as e:
            raise ValueError(f"OpenAPI spec 校验失败：{e}") from e

    paths = spec.get("paths") or {}
    if not paths:
        return []

    tools: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "delete", "patch", "head", "options"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{method}_{path}".replace("/", "_")
            tool_name = _normalize_op_id(op_id)
            description = op.get("summary") or op.get("description") or path
            parameters = _operation_parameters(spec, op, path_item)

            if schema_format == "openai_chat":
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": description,
                        "parameters": parameters,
                    },
                })
            elif schema_format == "openai_responses":
                tools.append({
                    "type": "function",
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters,
                })
            elif schema_format == "anthropic":
                tools.append({
                    "name": tool_name,
                    "description": description,
                    "input_schema": parameters,
                })
            else:
                raise ValueError(f"未知 schema_format: {schema_format}")

    return tools


__all__ = ["openapi_to_tools", "SchemaFormat"]
