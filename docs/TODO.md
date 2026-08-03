---
slug: todo
title: TODO
order: 10
icon: CHECKLIST_OUTLINED
---

# TODO

> v0.3.1 之后待办清单。优先级按"对生产可用性的影响"排序。
> 每条都标注当前状态（缺/部分/完成）和建议的实现方式。

## 优先级 P0（生产前必须）

### BaseAgent `aconversation_with_tool` 端到端测试

- **状态**：缺。`tests/test_base_agent_parity.py` 只测了 sync 路径，async 路径只通过 `test_async_smoke.py` 做了存在性检查。
- **建议**：在 `test_base_agent_parity.py` 加 3-5 项 async 路径测试（non-stream 纯文本 / stream 纯文本 / 工具调用 + text 混响）。

### `out` / `pack` 子类覆写行为

- **状态**：缺。当前测试只验证了 `pack` 默认实现构造的 content dict 正确，**没**验证"子类覆写 `out` 后，对话流程是否真的调到覆写方法"。
- **建议**：加 3 项：
  - 子类 `out` 收集所有事件 → 断言 `conversation_with_tool` 过程触发了 text / tool_call / tool_result / finish_task 四种事件
  - 子类 `out` 把 `task=True` 事件写到自定义 logger → 验证
  - async 路径同样覆盖

### `attempt_completion` 终止循环

- **状态**：缺。当前测试没断言 `attempt_completion` 被 LLM 调用后会立刻退出循环。
- **建议**：mock LLM 第一轮 `attempt_completion` → 断言函数立即返回 report_content，`real_call_count == 1`。

### ACL 拒绝

- **状态**：缺。`allowed_agents` 控制没单测覆盖。
- **建议**：注册工具时 `allowed_agents=["other_agent"]`，Agent 想调它时验证：
  - 抛 `ValueError("tool not found")` 或类似
  - 不会执行工具

### 工具超时转后台

- **状态**：缺。`tool_timeout` / `tool_max_workers` 行为没单测。
- **建议**：注册一个 `time.sleep(2)` 工具，Agent `tool_timeout=0.5` → 验证 LLM 拿到 `task_id` 描述、工具后台继续跑。

## 优先级 P1（生产可用性）

### MCP 测试

- **状态**：缺。MCP 端到端测试需要 spawn 子进程跑一个最小 MCP server，跨平台有坑。
- **建议**：
  1. 在 `tests/_mcp_mock.py` 起一个最小 MCP server（stdio JSON-RPC handler）
  2. `tests/test_mcp_bridge.py` 覆盖：会话创建 / tool schema 转换 / tool 调用 / 错误传播 / 关闭
  3. 主仓 `tests/test_api.py` 已有 `/mcp/*` HTTP 接口基础测试，可以作为 sanity check

### Skill 热加载（watchdog）

- **状态**：缺。`scan_and_register(auto_watch=True)` 启动 watchdog，文件变更时自动 reload。`tests/test_skill.py` 全部用 `auto_watch=False`。
- **建议**：
  1. `auto_watch=True` 启 observer
  2. 修改 SKILL.md
  3. 等 1-2 秒
  4. 断言 `get_skill(name).description` 变了

### `ask_for_help` 与队列集成

- **状态**：部分。`tests/test_agent_queue.py` 覆盖队列本身，但没测"Agent 通过 `ask_for_help` builtin_tool 走队列"端到端流程。
- **建议**：
  1. 两个 Agent（caller + callee）用同一个全局 queue
  2. caller.conversation_with_tool("请 callee 帮忙")
  3. 断言 callee.history 收到了消息、caller 拿到 callee 的回复

### Pydantic 参数校验

- **状态**：部分。`tests/test_pydantic_tools.py` 覆盖了 schema 推导，**没**覆盖"LLM 给错参数时框架行为"。
- **建议**：mock LLM 第一轮 `tool_use(input={"x": "not_a_number"})` → 断言 LLM 收到 `ValueError` 描述，第二轮重试。

### 异常流（LLM 500 / 网络断 / tool 抛异常）

- **状态**：缺。当前所有测试 mock 都返回成功响应。
- **建议**：
  1. mock 返回 500 → 验证 `http_utils` 重试 N 次后抛 `APIError`
  2. mock 在第 N+1 次返回成功 → 验证重试后能正常继续
  3. mock 注册的工具 `raise RuntimeError` → 验证 LLM 收到 `工具执行失败：...` 描述

## 优先级 P2（完善性）

### 并发

- **状态**：缺。`ask_for_help` 走 ThreadPool，没测过"同一 Agent 实例被多个 caller 并发调用"。
- **建议**：3 个 caller 同时 ask_for_help 同一 callee，验证 callee 串行处理（worker pool = 1）或并行（worker pool > 1）。

### XML 协议模式（fc_model=False）

- **状态**：缺。当前所有测试都走 `fc_model=True`（默认）。XML 模式（`BaseAgent.conversation_with_tool` 末尾的 `xml_pattern` 分支）完全没单测。
- **建议**：mock LLM 返回 `<ask_for_help><agent_id>x</agent_id><message>hi</message></ask_for_help>` → 验证框架解析 + 调用 + 续对话。

### `api_provider` 多种格式（Anthropic）

- **状态**：缺。`_endpoint()` 的 URL 拼接逻辑没单测。
- **建议**：
  - `api_provider="https://api.example.com"` → 期望 `https://api.example.com/v1/messages`
  - `api_provider="https://api.example.com/v1"` → 期望 `https://api.example.com/v1/messages`
  - `api_provider="https://api.example.com/v1/messages"` → 原样
  - 缺省 → 抛 `ValueError`

### `register_tool` 装饰器

- **状态**：部分。`tests/test_template_pool.py` 覆盖了 `@template_agent` 装饰器，但 `@register_agent`（已弃用）只在 `test_placeholder.py` 做了存在性检查。
- **建议**：3 项：装饰 + 弃用 warning / 已存在时 overwrite=False 报错 / description 参数透传。

### History 持久化（`new_load=False`）

- **状态**：缺。`Agent.__init__(new_load=False)` 保留 history 的行为没单测。
- **建议**：两次 `__init__`，第二次 `new_load=False` → 验证 `agent.history` 保留。

## 优先级 P3（清理）

### 测试隔离强化

- **状态**：部分。`tests/test_anthropic_agent.py` / `test_base_agent_parity.py` 用 `_clean_globals` autouse fixture 清 `agent_list` / `tool_registry`，但**没**清 `agent_queue` 全局队列。
- **建议**：在 conftest.py 加全局 autouse fixture，把 `agent_queue` / `skill_registry` / `mcp_bridge` 的全局状态也清掉。

### 跨平台

- **状态**：未知。`_llm_mock.py` 用 `ThreadingHTTPServer`，在 Linux/macOS/Windows 都应工作，但 CI 矩阵只跑 Python 3.10/3.11/3.12，**没**在多 OS 上验证。
- **建议**：CI matrix 加 `os: [ubuntu-latest, macos-latest, windows-latest]`。

### 性能压测

- **状态**：缺。无任何性能 / 并发压测。
- **建议**：
  1. mock LLM 固定延迟 → 跑 100 轮对话，记录 P50 / P99
  2. 100 个 ask_for_help 并发 → 记录 throughput

---

## 跟踪

每条 TODO 完成时同步更新本文件 + CHANGELOG [Unreleased] 节 + PR 描述。