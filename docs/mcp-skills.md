---
slug: mcp-skills
title: MCP 与 Skill
order: 8
icon: PUBLIC_OUTLINED
---

# MCP 与 Skill

> ⚠️ **v0.3.1 旧文档（已部分过时）** —— Skill 类化 / MCPClient 类化已独立出文档：
> - Skill 类化（`class TimeSkill(Skill): path="..."` + SKILL.md 自动发现）→ **[skill.md](skill.md)**
> - MCPClient 类（`class NotionMCP(MCPClient): server_path="..."`）→ **[mcp.md](mcp.md)**
> - 下文是 v0.3.1 时的概览，保留作历史参考，具体 API 以新文档为准。

MCP（Model Context Protocol）让 Agent 接入外部 stdio 工具服务器；Skill 是声明式的能力描述（agent 行为 / 工具 / 示例），兼容 Anthropic 的 `.claude/skills/` 目录规范。

## 能力成熟度

| 维度 | MCP | Skill |
|---|---|---|
| 核心 API | ✅ 可用 | ✅ 可用 |
| 端到端单测 | ⚠️ 缺（需要真实子进程） | ⚠️ 部分（`tests/test_skill.py`） |
| 边界 / 错误处理 | ⚠️ 部分 | ⚠️ 部分 |
| 热加载 | ❌ 不支持 | ✅ `watch_directory` |
| 生产案例 | ❌ 暂无 | ❌ 暂无 |

---

## Skill 开放标准

Skill 是声明式的能力描述（agent 行为 / 工具 / 示例），兼容 Anthropic 的 `.claude/skills/` 目录规范。

### Skill 目录结构

```text
.claude/skills/
└── weather_query/
    └── SKILL.md          # 单文件，frontmatter + body
```

`SKILL.md` 格式（YAML frontmatter + Markdown body）：

```markdown
---
name: weather_query
description: 查询某城市当前天气
allowed_agents: [weather]
---

# Weather Query

查询某个城市的实时天气。

## Examples

- 北京今天天气怎么样？
- 上海会下雨吗？

## Tool Schema

```json
{
  "type": "object",
  "properties": {
    "city": {"type": "string", "description": "城市名"}
  },
  "required": ["city"]
}
```
```

### 编程注册

```python
from tangyuanAI.skill import skill_registry

# 函数式注册（path 指向包含 SKILL.md 的目录）
skill_registry.register_skill(skill_dir=Path(".claude/skills/weather_query"))

# 查询
skill = skill_registry.get_skill("weather_query")
print(skill.get_full_description())
print(skill.get_tool_schema())
```

### 自动扫描

```python
skill_registry.scan_and_register(
    base_paths=[".claude/skills/", "examples/skills/"],
    auto_watch=True,  # 启用 watchdog 热加载
)
```

### system prompt 注入

`SkillRegistry.get_skills_prompt_text(agent_uuid)` 返回所有可见 skill 的描述，
在 `BaseAgent._build_system_prompt` / `AnthropicAgent._build_system_prompt` 末尾注入。

```python
# Agent 启动后，system prompt 自动包含：
# "你可以使用以下 Skill：
#  - weather_query: 查询某城市当前天气
#  - ..."
```

### 模板变量替换

Skill body 支持 `{{ var }}` 占位符，运行时通过 `Skill.render(arguments={...})` 替换：

```python
skill = skill_registry.get_skill("weather_query")
rendered = skill.render(arguments={"city": "北京"})
```

---

## MCP 协议桥接

```python
import tangyuanAI

# 自动拉起 MCP 服务器（stdin/stdout JSON-RPC），注册其所有工具
tangyuanAI.register_mcp_tools(
    server_path="mcp/weather_mcp/weather_server.py",
    allowed_agents=["weather"],
)
```

`MCPSessionPool` 内部走 stdio 启 server，热加载所有 tool schema 到 `tool_registry`，按 `allowed_agents` 过滤可见性。

### 会话管理

```python
from tangyuanAI.mcp_bridge import MCPSessionPool

pool = MCPSessionPool.get_global()
session = pool.get_or_create(server_path="mcp/.../server.py")
tools = session.list_tools()  # MCP 协议级 list

# 关闭
tangyuanAI.close_mcp_session("mcp/.../server.py")
tangyuanAI.close_all_mcp_sessions()
```

### 健康检查

```python
tangyuanAI.start_health_check(interval=300)  # 5 分钟一次
tangyuanAI.stop_health_check()
```

### 已知限制

- 每次 `get_or_create` 都新建 stdio 子进程；未做长连接池化
- tool schema 转换（`_convert_mcp_schema_to_openai`）只覆盖基本结构，复杂嵌套可能丢字段
- 错误处理：MCP server 崩溃时仅打印日志，Agent 调用会抛 `RuntimeError`；没有自动重启
- 鉴权：未实现 MCP `auth` 扩展

### 为什么测试覆盖薄

MCP 真实测试需要 spawn 子进程跑一个最小 MCP server，跨平台兼容性差（Windows stdio
行为 + asyncio 子进程策略有坑）。`tests/test_api.py` 在主仓里有 `/mcp/*` HTTP 接口的
基础测试，但**协议层端到端单测**尚未补齐。