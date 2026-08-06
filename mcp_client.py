# -*- coding: utf-8 -*-
"""
MCPClient 类（mcp_client.py）
=============================

**单 MCP server 客户端实例**。AI 可持有多个实例，各自管理生命周期。
复用 `mcp_bridge.py` 的 session 初始化 + schema 转换。

**用法 1：subclass + 类属性**：
```python
class NotionMCP(MCPClient):
    server_path = "./mcp_servers/notion.py"

m = NotionMCP()
async with m:
    tools = await m.list_tools()
    result = await m.call_tool("search", {"query": "..."})
```

**用法 2：直接构造**：
```python
m = MCPClient(server_path="./mcp_servers/github.py")
await m.connect()
```

**AI 集成**：
```python
m.register_tools()  # 把 MCP 工具注入 tool_registry，Agent 可调
```
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from .logging_config import logger

__all__ = ["MCPClient"]


class MCPClient:
    """单个 MCP server 客户端。"""

    # 类属性：subclass 设置
    server_path: Optional[str] = None
    name: Optional[str] = None

    def __init__(
        self,
        server_path: Optional[str] = None,
        name: Optional[str] = None,
    ):
        # 解析：显式参数 > 类属性
        self.server_path = server_path or self.server_path
        self.name = name or self.name or (
            Path(self.server_path).stem if self.server_path else "mcp"
        )

        self._session_info: Optional[dict[str, Any]] = None
        self._connected = False
        self._tools: list[Any] = []
        self._resources: list[Any] = []

    # === 生命周期 ===

    async def connect(self) -> "MCPClient":
        """启动 stdio 子进程 + 初始化 MCP 会话 + 缓存工具/资源列表。"""
        if self._connected:
            return self
        if not self.server_path:
            raise ValueError(
                "MCPClient 需要 server_path（构造参数或类属性）"
            )
        if not os.path.isfile(self.server_path):
            raise FileNotFoundError(f"MCP 服务器脚本不存在：{self.server_path}")

        from .mcp_bridge import _initialize_mcp_session

        self._session_info = await _initialize_mcp_session(self.server_path)
        self._tools = self._session_info.get("tools", [])
        self._resources = self._session_info.get("resources", [])
        self._connected = True
        logger.info(f"MCPClient 已连接: {self.name} @ {self.server_path}（{len(self._tools)} 个工具）")
        return self

    async def close(self) -> None:
        """关闭 MCP 会话 + stdio 子进程。"""
        if self._session_info is not None:
            try:
                await self._session_info["session"].__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"close session: {e}")
            try:
                await self._session_info["context"].__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"close context: {e}")
            self._session_info = None
        self._connected = False
        self._tools = []
        logger.info(f"MCPClient 已关闭: {self.name}")

    # === 上下文管理器 ===

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def __enter__(self) -> "MCPClient":
        # 同步上下文（调 connect 的同步版）
        asyncio.run(self.connect())
        return self

    def __exit__(self, *exc: Any) -> None:
        asyncio.run(self.close())

    # === 工具 ===

    @property
    def connected(self) -> bool:
        return self._connected

    async def list_tools(self) -> list[dict[str, Any]]:
        """返回工具列表（OpenAI schema 格式）。"""
        await self.connect()
        from .mcp_bridge import _convert_mcp_schema_to_openai
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": _convert_mcp_schema_to_openai(
                    getattr(t, "inputSchema", None) or {}
                ),
            }
            for t in self._tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用 MCP 工具，返回原始内容。"""
        await self.connect()
        if self._session_info is None:
            raise RuntimeError("MCP 会话未初始化")
        session = self._session_info["session"]
        result = await session.call_tool(name, arguments)
        return result

    async def read_resource(self, name: str) -> Any:
        """读取 MCP 资源。"""
        await self.connect()
        if self._session_info is None:
            raise RuntimeError("MCP 会话未初始化")
        session = self._session_info["session"]
        result = await session.read_resource(name)
        return result

    # === 注册到 tool_registry（Agent 可调） ===

    def register_tools(self, allowed_agents: Optional[list[str]] = None) -> list[str]:
        """把 MCP 工具注册到 tool_registry。Returns: 注册的工具名列表。"""
        from .agent_tool import tool_registry
        from .mcp_bridge import _convert_mcp_schema_to_openai

        if not self._connected:
            asyncio.run(self.connect())

        names: list[str] = []
        for t in self._tools:
            tool_name = f"{self.name}_{t.name}"
            params = _convert_mcp_schema_to_openai(
                getattr(t, "inputSchema", None) or {}
            )
            try:
                decorator = tool_registry.register_tool(
                    allowed_agents=allowed_agents,
                    description=t.description or "",
                    name=tool_name,
                    parameters=params,
                )
                decorator(self._make_sync_wrapper(t.name))
                names.append(tool_name)
            except Exception as e:
                logger.error(f"注册 MCP 工具失败 {tool_name}: {e}")
        return names

    def _make_sync_wrapper(self, name: str):
        """同步包装器：用共享事件循环调 async call_tool。"""
        from .mcp_bridge import get_or_create_event_loop

        def sync_wrapper(**kwargs) -> str:
            loop = get_or_create_event_loop()
            result = loop.run_until_complete(self.call_tool(name, kwargs))
            content = getattr(result, "content", None) or ""
            if isinstance(content, list):
                return "\n".join(str(c) for c in content)
            return str(content)

        return sync_wrapper

    def __repr__(self) -> str:
        state = "connected" if self._connected else "disconnected"
        return f"MCPClient(name={self.name!r}, server_path={self.server_path!r}, {state})"
