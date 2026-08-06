# -*- coding: utf-8 -*-
"""
A2A 协议层（kb/a2a_protocol.py）
================================

Google A2A（Agent-to-Agent）协议的 JSON-RPC 2.0 消息构造/解析 + Agent Card schema。
纯数据结构，不依赖 aiohttp / httpx（那在 exporter / client 层）。

**Agent Card**（`/.well-known/agent.json`）：
```json
{
  "name": "agent-name",
  "description": "...",
  "url": "http://host:port/a2a/v1",
  "version": "1.0",
  "capabilities": {"streaming": true, "pushNotifications": false},
  "skills": [],
  "protocolVersion": "0.2.1"
}
```

**tasks/send**（JSON-RPC 2.0）：
```json
{"jsonrpc": "2.0", "id": "1", "method": "tasks/send",
 "params": {"id": "task-123",
            "message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}}}
```
响应：
```json
{"jsonrpc": "2.0", "id": "1",
 "result": {"id": "task-123", "status": {"state": "completed"},
            "artifacts": [{"kind": "text", "text": "hi there"}]}}
```
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

__all__ = [
    "make_json_rpc_request",
    "make_json_rpc_response",
    "make_json_rpc_error",
    "parse_json_rpc",
    "make_agent_card",
    "make_text_message",
    "extract_text_from_artifacts",
]


def make_json_rpc_request(method: str, params: dict[str, Any], rpc_id: str | None = None) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 请求。"""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id or uuid.uuid4().hex,
        "method": method,
        "params": params,
    }


def make_json_rpc_response(result: Any, rpc_id: str | None = None) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 成功响应。"""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": result,
    }


def make_json_rpc_error(code: int, message: str, rpc_id: str | None = None) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 错误响应。"""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


def parse_json_rpc(data: dict[str, Any]) -> dict[str, Any]:
    """校验 JSON-RPC 2.0 消息，返回规范化 dict。

    Raises:
        ValueError: 缺少 jsonrpc / method / params
    """
    if not isinstance(data, dict):
        raise ValueError("JSON-RPC 消息必须是 object")
    if data.get("jsonrpc") != "2.0":
        raise ValueError(f"jsonrpc 必须为 '2.0'，got {data.get('jsonrpc')!r}")
    if "method" not in data:
        raise ValueError("JSON-RPC 消息缺 method")
    return data


def make_agent_card(
    name: str,
    description: str,
    url: str,
    *,
    skills: Optional[list[dict[str, Any]]] = None,
    capabilities: Optional[dict[str, Any]] = None,
    protocol_version: str = "0.2.1",
) -> dict[str, Any]:
    """构造 Agent Card。"""
    return {
        "name": name,
        "description": description,
        "url": url,
        "version": "1.0",
        "capabilities": capabilities or {"streaming": True, "pushNotifications": False},
        "skills": skills or [],
        "protocolVersion": protocol_version,
    }


def make_text_message(text: str, role: str = "user") -> dict[str, Any]:
    """构造 A2A message（单个 text part）。"""
    return {
        "role": role,
        "parts": [{"kind": "text", "text": text}],
    }


def extract_text_from_artifacts(artifacts: list[dict[str, Any]]) -> str:
    """从 A2A task 的 artifacts 提取文本。"""
    parts: list[str] = []
    for a in artifacts or []:
        for part in a.get("parts", []) or []:
            if part.get("kind") == "text" and part.get("text"):
                parts.append(part["text"])
    return "\n".join(parts)
