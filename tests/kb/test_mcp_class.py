# -*- coding: utf-8 -*-
"""
MCPClient 类测试（tests/kb/test_mcp_class.py）
=============================================

验证 #5：MCP → MCPClient 类。
- subclass + 类属性 server_path
- 生命周期：connect / close / async context manager
- list_tools / call_tool / read_resource
- register_tools 注入 tool_registry
- 缺 server_path 报错
- 不 spawn 真子进程（mock _initialize_mcp_session）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tangyuanAI.mcp_client import MCPClient


def _fake_session_info(tools=None):
    """构造假的 session_info（mock _initialize_mcp_session 的返回）。"""
    session = MagicMock()
    session.call_tool = AsyncMock(return_value=MagicMock(content="tool result"))
    session.read_resource = AsyncMock(return_value=MagicMock(contents=["res"]))

    def _tool(name, desc="", schema=None):
        t = MagicMock()
        t.name = name
        t.description = desc
        t.inputSchema = schema or {"type": "object", "properties": {}}
        return t

    return {
        "session": session,
        "transport": None,
        "context": AsyncMock(),
        "tools": tools or [_tool("search", "搜索", {"type": "object", "properties": {"q": {"type": "string"}}}), _tool("get")],
        "resources": [],
        "initialized": True,
        "server_path": "./fake.py",
        "last_used": 0,
    }


class TestMCPClient:
    @patch("tangyuanAI.mcp_bridge._initialize_mcp_session")
    async def test_subclass_with_server_path(self, mock_init, tmp_path):
        """subclass + 类属性 server_path。"""
        mock_init.return_value = _fake_session_info()
        fake_path = tmp_path / "notion.py"
        fake_path.write_text("", encoding="utf-8")

        class NotionMCP(MCPClient):
            server_path = str(fake_path)  # 类属性

        m = NotionMCP()  # 无参数
        assert m.server_path == str(fake_path)
        assert m.name == "notion"  # 默认从 server_path stem
        await m.connect()
        assert m.connected

    @patch("tangyuanAI.mcp_bridge._initialize_mcp_session")
    async def test_async_context_manager(self, mock_init):
        """async with m: 自动 connect/close。"""
        mock_init.return_value = _fake_session_info()
        import tempfile
        fake = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        fake.close()
        async with MCPClient(server_path=fake.name) as m:
            assert m.connected
            tools = await m.list_tools()
            assert len(tools) == 2
            assert tools[0]["name"] == "search"
        assert not m.connected

    @patch("tangyuanAI.mcp_bridge._initialize_mcp_session")
    async def test_call_tool(self, mock_init, tmp_path):
        """call_tool 走 session.call_tool。"""
        mock_init.return_value = _fake_session_info()
        fake = tmp_path / "fake.py"
        fake.write_text("", encoding="utf-8")
        m = MCPClient(server_path=str(fake))
        await m.connect()
        result = await m.call_tool("search", {"q": "hello"})
        assert result.content == "tool result"

    @patch("tangyuanAI.mcp_bridge._initialize_mcp_session")
    async def test_register_tools(self, mock_init, tmp_path):
        """register_tools 注入 tool_registry。"""
        mock_init.return_value = _fake_session_info()
        from tangyuanAI.agent_tool import tool_registry
        fake = tmp_path / "fake.py"
        fake.write_text("", encoding="utf-8")
        m = MCPClient(server_path=str(fake), name="notion")
        await m.connect()
        names = m.register_tools()
        assert "notion_search" in names
        assert "notion_get" in names
        assert "notion_search" in tool_registry._tools

    async def test_no_server_path_raises(self):
        """无 server_path → connect 报错。"""
        m = MCPClient()
        with pytest.raises(ValueError, match="server_path"):
            await m.connect()

    async def test_missing_file_raises(self, tmp_path):
        """server_path 指向不存在文件 → 报错。"""
        m = MCPClient(server_path=str(tmp_path / "nope.py"))
        with pytest.raises(FileNotFoundError):
            await m.connect()

    @patch("tangyuanAI.mcp_bridge._initialize_mcp_session")
    async def test_close_releases(self, mock_init, tmp_path):
        """close 后 connected=False，再 connect 可重连。"""
        mock_init.return_value = _fake_session_info()
        fake = tmp_path / "fake.py"
        fake.write_text("", encoding="utf-8")
        m = MCPClient(server_path=str(fake))
        await m.connect()
        await m.close()
        assert not m.connected
        # 可重连
        await m.connect()
        assert m.connected
