# dumplingsAI

> 一个轻量、模块化的多智能体协作框架，让 LLM 像"公司团队"一样分工完成任务。

[![PyPI](https://img.shields.io/pypi/v/dumplingsAI.svg)](https://pypi.org/project/dumplingsAI/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-green.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://github.com/Secret-Dumplings/dumplingsAI/actions/workflows/python-package.yml/badge.svg)](https://github.com/Secret-Dumplings/dumplingsAI/actions)

---

## 特性一览

- **多协议 Agent**：`BaseAgent`（OpenAI-compatible Chat Completions）+ `AnthropicAgent`（Anthropic Messages API），同一份 `agent_list` 共用
- **声明式注册**：`@register_agent`（已弃用）/ `@template_agent` + `activate_template` / `@tool_registry.register_tool`，单行注册
- **统一内置 schema**：`@builtin_tool` 装饰器从签名+类型注解自动推导，零硬编码
- **跨 Agent 协作**：`ask_for_help` / `list_agents` / `attempt_completion` / `reload` 四个内建工具
- **模板池管理**（v0.3.0+）：`list_templates` / `activate_template` / `deactivate_template` / `register_template` —— `BaseAgent` / `AnthropicAgent` 双协议对齐
- **MCP 协议桥接**：标准 stdio MCP 服务器自动接入
- **Skill 开放标准**：兼容 `.claude/skills/` 目录，热加载
- **细粒度权限 ACL**：每个工具可指定允许使用的 Agent 列表
- **钩子系统**：`register_tool_hook(event_type, ...)` 监听工具调用前/后/错误
- **`pack` 输出事件总线**（v0.3.1+）：`BaseAgent` / `AnthropicAgent` 同步+异步两条对话路径都走 `self.pack(...)` → `self.out(content)`，双协议输出接口完全对称
- **Agent 状态持久化**（v0.4.0+）：`.duas` 文件格式（人类可读 / git diff 友好）+ 可插拔后端（FileBackend 默认 / SQLiteBackend 实验）+ 实时自动保存（env var 或 `configure()` API）

---

## 安装

```bash
pip install dumplingsAI
```

需要 Python 3.10+。

---

## 文档站

在线文档：**https://docs.dumplingsai.secret-dumplings.xin**（Cloudflare Pages，push 自动构建）

- 文档源在 `docs/`（YAML frontmatter 驱动，新增文档只需加带 frontmatter 的 .md）
- 文档站代码在 `docs-site/`（VitePress + BBDDFF 浅蓝主题，**不入 PyPI 包**）
- 本地跑文档站：`cd docs-site && pnpm install && pnpm dev`

---

## 快速开始

### 1. 准备 API Key

```bash
export API_KEY="sk-..."                    # OpenAI 协议
export ANTHROPIC_API_KEY="sk-ant-..."      # Anthropic 协议
```

### 2. 第一个 Agent

```python
import os
import dumplingsAI

@dumplingsAI.tool_registry.register_tool(
    allowed_agents=["weather"],   # None 或 [] 表示所有 Agent 可用
    description="查询某城市当前天气",
    name="get_weather",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"],
    },
)
def get_weather(city: str) -> str:
    return f"{city}今天晴，25°C"

@dumplingsAI.register_agent("agent-uuid-1", "weather", "天气小助手")
class WeatherAgent(dumplingsAI.BaseAgent):
    """走 OpenAI-compatible Chat Completions 的天气 Agent。"""
    prompt = "你是天气助手，使用 get_weather 工具查询天气。"
    api_provider = "https://api.example.com/v1/chat/completions"
    model_name = "qwen3.5-plus"
    api_key = os.getenv("API_KEY")

if __name__ == "__main__":
    agent = dumplingsAI.agent_list["weather"]
    agent.conversation_with_tool("北京今天天气怎么样？")
```

### 3. 多协议混用

```python
from dumplingsAI.anthropic_agent import AnthropicAgent

@dumplingsAI.register_agent("agent-uuid-2", "reviewer", "走 Claude 协议的评审 Agent")
class ReviewerAgent(AnthropicAgent):
    prompt = "你是评审助手。完成工作后用 attempt_completion 汇报。"
    api_provider = "https://api.anthropic.com"
    model_name = "claude-3-5-sonnet-latest"
    api_key = os.getenv("ANTHROPIC_API_KEY")

# 同一份 agent_list，OpenAI / Anthropic Agent 互通
weather = dumplingsAI.agent_list["weather"]
reviewer = dumplingsAI.agent_list["reviewer"]
reviewer.conversation_with_tool(
    f"刚才 weather Agent 说北京晴 25°C，请评审"
)
```

---

## 核心概念

### Agent 注册

两种写法：v0.3.0+ 推荐 `@template_agent` + `activate_template` 模板池模式；旧的 `@register_agent` 已弃用但仍兼容。

```python
# 写法 1：模板池（v0.3.0+ 推荐）—— 类只入池，运行时再 activate
from dumplingsAI import template_agent
from dumplingsAI.Agent_list import activate_template

@template_agent("my_agent", uuid="my-uuid", description="一句话说明 Agent 用途")
class MyAgent(dumplingsAI.BaseAgent):
    prompt    = "..."
    api_provider = "..."
    model_name   = "..."
    api_key      = "..."

# 显式激活（也可以在 LLM 工具调用时由 agent 自己 activate）
activate_template("my_agent")
```

```python
# 写法 2：立即注册（v0.3.0 起已弃用，import 时 logger.warning 提示迁移）
@dumplingsAI.register_agent("my-uuid", "my_agent", "一句话说明 Agent 用途")
class MyAgent(dumplingsAI.BaseAgent):
    prompt       = "..."   # 系统提示词
    api_provider = "..."   # API 端点
    model_name   = "..."   # 模型名
    api_key      = "..."   # 鉴权
    fc_model     = True    # 是否启用 Function Calling
    stream       = True    # 是否流式响应
    timeout      = 60      # 单请求超时
    max_retries  = 2       # 最大重试次数
```

### 工具注册

两种写法等价：

```python
# 写法 1：装饰器 + JSON Schema（传统）
@dumplingsAI.tool_registry.register_tool(
    allowed_agents=["my_agent"],
    name="add",
    description="求两数之和",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    },
)
def add(a: float, b: float) -> float:
    return a + b
```

```python
# 写法 2：内置工具的 schema 自动从签名/类型注解推导
from dumplingsAI import builtin_tool

@builtin_tool(
    description="求两数之和",
    params={"a": "第一个加数", "b": "第二个加数"},
)
def add(self, a: float, b: float) -> float:
    return a + b
```

### Agent 间的协作

每个 Agent 自带 8 个内建工具（v0.3.0+ 4 个协作工具 + v0.3.0+ 4 个模板管理工具，`BaseAgent` / `AnthropicAgent` 双协议一致）：

| 工具 | 用途 |
|------|------|
| `ask_for_help(agent_id, message)` | 委派任务给其他 Agent |
| `list_agents()` | 列出所有可协作的 Agent |
| `attempt_completion(report_content)` | 标记任务完成 |
| `reload()` | 重新拉取工具/技能列表 |
| `list_templates(name="")` | 查询模板池（v0.3.0+） |
| `activate_template(name)` | 把池中模板实例化并写入 `agent_list`（v0.3.0+） |
| `deactivate_template(name)` | 从 `agent_list` 移除实例（保留在池中）（v0.3.0+） |
| `register_template(name, description="")` | 占位说明：注册 cls 必须在 Python 代码侧完成（v0.3.0+） |

无需手写 prompt 教 LLM 怎么调——框架已把工具描述注入到 system prompt 里。

> **注意**：`allowed_agents` 必须传 agent **name** 而不是 uuid。`tool_registry.check_permission` 内部
> 会先做 uuid→name 翻译再比对。详见 `agent_tool.check_permission`。

### 钩子

```python
class MyAgent(dumplingsAI.BaseAgent):
    def __init__(self):
        super().__init__()
        self.register_tool_hook(self._audit)

    def _audit(self, event_type, tool_name, tool_args, tool_result, task_id):
        # event_type: 'before' | 'after' | 'error'
        if event_type == 'error':
            logger.error(f"工具 {tool_name} 失败：{tool_result}")
```

### MCP 桥接

```python
import dumplingsAI

# 自动拉起 MCP 服务器并注册其所有工具
dumplingsAI.register_mcp_tools(
    server_path="mcp/weather_mcp/weather_server.py",
    allowed_agents=["weather"],
)
```

---

## API 参考

```python
from dumplingsAI import (
    BaseAgent,           # OpenAI 协议 Agent 基类
    builtin_tool,        # 内置工具装饰器
    register_agent,      # Agent 注册装饰器
    tool_registry,       # 工具注册器实例
    agent_list,          # 已注册 Agent 字典
    register_mcp_tools,  # MCP 工具注册
    skill_registry,      # Skill 注册表
    # AnthropicAgent 走子模块路径：
    # from dumplingsAI.anthropic_agent import AnthropicAgent
)
```

详见 [`docs/PROJECT.md`](https://github.com/Secret-Dumplings/AI_Company/blob/main/docs/PROJECT.md)（仓库内的 SDK 差距分析 + 完整设计文档）。

---

## 示例

仓库自带完整示例：

- `examples/basic_agent/agent_example.py` — 单 Agent 基础用法
- `examples/multi_agent/ask_for_help_example.py` — 多 Agent 协作
- `examples/anthropic_agent/agent_example.py` — Anthropic 协议示例
- `tests/test_placeholder.py` — 冒烟测试（验证包能 import、装饰器工作）
- `tests/test_template_pool.py` — 模板池 API 单测（v0.3.0+）
- `tests/test_anthropic_agent.py` / `tests/test_base_agent_parity.py` — 走 `_llm_mock` 的协议层端到端单测（v0.3.1+）

运行：

```bash
git clone https://github.com/Secret-Dumplings/AI_Company.git
cd AI_Company
uv sync
uv run python examples/basic_agent/agent_example.py
```


---

## 开发与测试

```bash
git clone https://github.com/Secret-Dumplings/AI_Company.git
cd AI_Company
uv sync --group dev
uv run pytest Dumplings/tests/ -v
uv run ruff check Dumplings/
```

CI 在 `python-package.yml`，自动跑 ruff + pytest on Python 3.10 / 3.11 / 3.12。

### Mock 基础设施（v0.3.1+）

`Dumplings/tests/_llm_mock.py` 提供 OpenAI Chat Completions + Anthropic Messages API 双协议 mock，让 Agent 走完整 wire 协议（构造 payload → 序列化 → 解析回来）做端到端单测，无需开真实 LLM：

- 按请求 body 的 `stream` 字段自动分派 JSON / SSE
- 多轮：每条请求消耗队列里一个响应工厂
- `_connectivity` 探测请求短路（不消耗队列）
- 请求日志：可断言"调了几次 / 每次发了什么"

完整用法见 `tests/test_anthropic_agent.py`（17 项）和 `tests/test_base_agent_parity.py`（6 项）。

---

## 贡献

欢迎 PR / Issue。提交前请跑 `uv run ruff check` + `uv run pytest`。

---

## 许可证

Apache License 2.0

Copyright 2025-2026 [Secret Dumplings](https://github.com/Secret-Dumplings)

```
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.