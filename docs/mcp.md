---
slug: mcp
title: MCP 客户端（Model Context Protocol）
order: 9
icon: PUBLIC_OUTLINED
---

# MCP 客户端（Model Context Protocol）

> **v1.0.0+**。MCP 让 Agent 接入外部 stdio 工具服务器（本地进程）。tangyuanAI 支持 `MCPClient` 类（多实例、AI 可持有）和旧的全局 `register_mcp_tools` API。

## 快速上手：MCPClient（类化）

```python
import tangyuanAI as t
from tangyuanAI.mcp_client import MCPClient

# 1. 类化：subclass + 类属性
class NotionMCP(MCPClient):
    server_path = "./mcp_servers/notion.py"   # 类属性：MCP server 脚本路径

m = NotionMCP()
async with m:
    tools = await m.list_tools()              # → [{name, description, inputSchema}, ...]
    result = await m.call_tool("search", {"query": "meeting notes"})
    print(result)
```

**用法 2：直接构造**：
```python
m = MCPClient(server_path="./mcp_servers/github.py", name="github")
await m.connect()
tools = await m.list_tools()
await m.call_tool("list_repos", {"owner": "secret-tangyuan"})
await m.close()
```

**注册给 Agent（tool bridge）**：
```python
names = m.register_tools()     # → ['notion_search', 'notion_get', ...]
# Agent 通过 Function Calling 直接调用
```

## 旧 API（全局函数，向后兼容）

```python
import tangyuanAI as t
# 一行调（内部 spawn stdio 子进程 + 注册工具）
n = t.register_mcp_tools("./mcp_servers/github.py")
# n = 注册的工具数

t.close_mcp_session("./mcp_servers/github.py")
t.get_session_info()              # → 列出所有会话
t.close_all_mcp_sessions()
```

## MCPServer 方言（MCP 协议本身是标准的）

MCP server 是一个标准 stdio JSON-RPC 程序，与框架无关。部署到 `mcp_servers/` 目录即可。

## 注意

- `server_path` 指向本地脚本（`.py` 或 `.js`），MCPClient 内部用 stdio spawn 子进程
- `async with m:` 自动 connect/close（释放 stdio 进程）
- 多个 MCPClient 互不干扰（每个实例一个独立进程）