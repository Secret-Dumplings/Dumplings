# dumplingsAI 文档

dumplingsAI 是一个轻量、模块化的多智能体协作框架，让 LLM 像"公司团队"一样分工完成任务。

同一份 `agent_list` 同时容纳 **OpenAI 协议 Agent**（`BaseAgent`）与 **Anthropic 协议 Agent**（`AnthropicAgent`），通过 `Agent` 工厂基类 + `protocol` 字段统一选择。

## 文档导航

| 文档 | 内容 |
|---|---|
| [getting-started.md](getting-started.md) | 安装、API Key、第一个 Agent |
| [agent-registration.md](agent-registration.md) | 两种注册写法：模板池（推荐）vs `@register_agent`（弃用） |
| [tools.md](tools.md) | 工具注册：`@tool_registry.register_tool` vs `@builtin_tool` |
| [builtin-tools.md](builtin-tools.md) | 8 个内建工具一览（`ask_for_help` / `attempt_completion` / 模板管理等） |
| [protocols.md](protocols.md) | OpenAI 协议 vs Anthropic 协议、`Agent` 工厂基类、双协议对称性 |
| [output-and-hooks.md](output-and-hooks.md) | `pack` / `out` 输出事件总线、工具调用钩子 |
| [mcp-skills.md](mcp-skills.md) | MCP 协议桥接、Skill 开放标准（**测试功能**） |
| [testing.md](testing.md) | Mock 基础设施（`_llm_mock.py`）、端到端单测写法 |
| [TODO.md](TODO.md) | 待办：单测覆盖 / 边界处理 / 生产就绪检查清单 |

## 仓库结构

```
Dumplings/                       # 主包：dumplingsAI（PyPI）
├── Agent_Base_.py               # BaseAgent（OpenAI 协议）
├── anthropic_agent.py           # AnthropicAgent（Anthropic 协议）
├── Agent_list.py                # agent_list + 模板池（register_template / activate_template）
├── agent_tool.py                # @builtin_tool + tool_registry + ACL
├── agent_queue.py               # ask_for_help 跨 Agent 调用队列（防超限递归）
├── llm_transport.py             # HTTP transport 抽象 + OpenAI / Anthropic 实现
├── tool_runner.py               # 工具执行 ThreadPool + 超时转后台
├── http_utils.py                # 退避重试 HTTP 客户端
├── anthropic_agent.py           # Anthropic 协议 Agent
├── skill.py / skill_bridge.py   # Skill 注册 + 热加载
├── mcp_bridge.py                # stdio MCP 桥接
├── cli.py                       # `dumplings` CLI
└── tests/
    ├── _llm_mock.py             # OpenAI + Anthropic 协议 mock（v0.3.1+）
    ├── test_anthropic_agent.py  # Anthropic 协议层端到端单测
    ├── test_base_agent_parity.py# BaseAgent / AnthropicAgent 对称性单测
    ├── test_template_pool.py    # 模板池 API 单测
    ├── test_agent_queue.py      # ask_for_help 队列单测
    └── ...
```

## 核心约定

- **双键 agent_list**：`agent_list[uuid]` 和 `agent_list[name]` 命中同一实例。
- **XML 标签协议**：Agent ↔ Agent、Agent ↔ Tool 走 `<ask_for_help>` / `<attempt_completion>` 等 XML 标签（除非 `fc_model=True` 走原生 function calling）。
- **工具 ACL**：`register_tool(allowed_agents=[...])` 显式列出允许的 agent；`None` / `[]` 表示全局可用。
- **`allowed_agents` 用 agent name 不用 uuid**（`check_permission` 内部会做 uuid→name 翻译，详见 [tools.md](tools.md#acl-注意事项)）。