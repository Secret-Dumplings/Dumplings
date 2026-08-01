# -*- coding: utf-8 -*-
"""
MCP 集成基础 smoke 测试。

完整 E2E（spawn 子进程跑真实 MCP server）受限于跨平台 stdio + asyncio 子进程策略，
未在大规模压测，详见 ``docs/TODO.md`` 的 MCP 区块。
本测试只覆盖：

- MCP 模块可 import，核心 API 存在
- register_mcp_tools 在坏路径下不崩（404 / nonexistent）
- get_session_info / close_mcp_session 基础调用
"""
from __future__ import annotations

import pytest


def test_mcp_module_imports():
    """dumplingsAI.mcp_bridge 可 import"""
    from dumplingsAI import mcp_bridge
    assert mcp_bridge is not None


def test_mcp_top_level_api_exists():
    """顶层 MCP API 都存在"""
    import dumplingsAI
    for name in ("register_mcp_tools", "register_mcp_tools_async",
                 "close_mcp_session", "close_mcp_session_sync",
                 "close_all_mcp_sessions", "close_all_mcp_sessions_sync",
                 "get_session_info", "start_health_check", "stop_health_check"):
        assert hasattr(dumplingsAI, name), f"missing {name}"


def test_register_mcp_tools_with_nonexistent_path_raises():
    """场景：用户给了一个不存在的 server_path → 框架应给出清晰错误，不静默成功"""
    import dumplingsAI
    # 同步版本
    with pytest.raises(Exception):  # 可能是 FileNotFoundError 或 RuntimeError
        dumplingsAI.register_mcp_tools(server_path="/nonexistent/path/to/server.py")


def test_get_session_info_empty():
    """无活跃 session → 不崩，返回结构"""
    import dumplingsAI
    info = dumplingsAI.get_session_info()
    assert isinstance(info, dict)
    # session 总数应该是 0
    assert info.get("total", 0) == 0 or len(info.get("sessions", [])) == 0


def test_close_mcp_session_nonexistent_returns_false():
    """关不存在的 session → 返回 False，不抛"""
    import dumplingsAI
    # 同步 close：返回 bool
    result = dumplingsAI.close_mcp_session_sync("/nonexistent/server.py")
    assert result is False


def test_close_all_mcp_sessions_empty():
    """无活跃 session 时 close all → 返 0"""
    import dumplingsAI
    closed = dumplingsAI.close_all_mcp_sessions_sync()
    assert closed == 0
