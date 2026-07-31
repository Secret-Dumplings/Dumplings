# Changelog

dumplingsAI 的所有显著变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **Agent 状态持久化（v0.4.0+）—— 可插拔后端架构**
  - 自定义 `.duas` 文件格式（INI 头 `[META]/[CONFIG]/[STATE]` + JSONL 体 `[HISTORY]`）
    - 人类可读 / git diff 友好 / 可手编
    - `schema_version` 自动从 `dumplingsAI.__version__` 读，pyproject bump 自动同步
    - `api_key` 不存明文，只存 `api_key_env`（env var 名），加载时 `os.getenv` 重新解析
  - 顶层 API：
    - `save_state(agent, key, *, backend=None)` / `load_state(key, *, backend=None)` /
      `delete_state(key, *, backend=None)` / `list_states(*, backend=None)`
    - `export_state_string(agent)` / `load_state_string(s)` —— 字符串 API（不落盘）
    - `agent.save_state(key)` / `Agent.load_state(key)` —— 实例方法 wrapper
  - 内置后端：
    - `FileBackend`（默认、成熟）：每个 key 一个 `.duas` 文件
    - `SQLiteBackend`（**实验性**）：sqlite3 单表 `sessions`，v0.4.0 初次实现未压测
  - 插件协议 `PersistenceBackend`（4 方法：save/load/delete/list_keys）
    - `register_backend(name, backend, set_as_default=False)` 注册自定义后端
    - 可接入 Redis / Postgres / S3 / 任何 KV 存储
- **实时自动保存（v0.4.0+）**
  - import 时读取环境变量配置（默认关闭）：
    - `DUMPLINGS_PERSISTENCE=on|off`
    - `DUMPLINGS_PERSISTENCE_BACKEND=file|sqlite`
    - `DUMPLINGS_PERSISTENCE_DIR=./sessions` （file 后端）
    - `DUMPLINGS_PERSISTENCE_DB=./sessions.db` （sqlite 后端）
    - `DUMPLINGS_PERSISTENCE_KEY=uuid|name`
  - 编程配置：`dumplingsAI.configure(enabled=, backend=, base_dir=, db_path=, key_strategy=)`
  - `@_auto_save` / `@_auto_save_async` 装饰器包了 `BaseAgent` / `AnthropicAgent`
    的 `conversation_with_tool` / `aconversation_with_tool`；用 `_conv_depth` 计数器
    保证最外层调用退出时保存一次，FC 模式递归不重复保存
  - 默认 key 策略 = `uuid`（每个 agent 一份"当前状态"），可切到 `name`

### Changed
- **`Agent_Base_.py` 加 `from __future__ import annotations`**：启用 PEP 563
  注解惰性求值，解决前向引用

### Tests
- **新增 `tests/test_persistence.py`（37 项）**
  - 导出格式 / 多行 prompt 转义 / `schema_version` 自动读取
  - FileBackend：roundtrip / delete / list / 路径穿越保护
  - SQLiteBackend：roundtrip / delete / list
  - 插件注册 / 重复注册 / 未知 backend
  - 类身份解析：成功 / 降级到 agent_list / 失败抛 `AgentNotFoundError`
  - 自动保存：默认关闭 / configure 启用 / env var 启用 / 异步路径
  - 装饰器：conversation_with_tool 退出时保存 / async / FC 递归不重复保存
  - key_strategy 切换 / 持久化失败不阻塞对话
- **完整 `pytest tests/` 套件 148/148 通过，无回归**（112 旧 + 36 新）

## [0.3.1] - 2026-07-30

### Fixed
- **`AnthropicAgent.conversation_with_tool(stream=False)` 丢字**
  - v0.3.0 bug：non-stream 模式下 LLM 返回的文本只累积到 `full_text`，但没进 `assistant_blocks`，
    最终 `return "".join(b.get("text", "") for b in last if b.get("type") == "text")` 永远空串
  - 修复：non-stream 分支在 `if llm_rsp.text:` 里同步 `assistant_blocks.append({"type": "text", "text": llm_rsp.text})`
  - 异步版 `aconversation_with_tool` 同样修复
- **`BaseAgent.conversation_with_tool` 同步多轮工具调用吞掉 LLM 最终回复**
  - v0.3.0 bug：tool=True 递归到末尾时 `if tool: return work_history[-1].get("content")` 把上轮 tool_result 当最终答案
  - 修复：递归到末尾应返回当前轮 LLM 的 `full_content`（FC 模式递归场景下 LLM 已经回过 LLM 那一句才是答案）

### Added
- **`AnthropicAgent` 补齐 4 个模板管理 builtin_tool**（v0.3.0 仅 `BaseAgent` 暴露，v0.3.1 补齐 `AnthropicAgent`）
  - `list_templates(name="")` / `activate_template(name)` / `deactivate_template(name)` / `register_template(name, description="")`
  - 与 BaseAgent 完全对称 —— 两协议公开 API 集合一致
- **`AnthropicAgent` 新增 `pack` 方法**（与 `BaseAgent.pack` 同款）
  - 把事件打包成带 `ai_uuid` / `ai_name` / `task_id` / `timestamp` 的 content dict 再调 `out`
  - 同步 / 异步两个 `conversation_with_tool` 内部从 `self.out({...})` 全部切到 `self.pack(...)`
  - 想接管输出行为请覆写 `out`，不要覆写 `pack`（与 BaseAgent 同样的约定）
- **`AnthropicAgent` 新增 `get_all_available_tools` 方法**（与 `BaseAgent` 同款）

### Changed
- **`BaseAgent` / `AnthropicAgent` 公开方法补全类型注解**
  - `out(content: dict) -> None` / `pack(...) -> None` / `conversation_with_tool(messages, tool: bool, images)`
  - `_generate_task_id() -> str` / `_get_timestamp() -> int`

### Tests
- **新增 `tests/_llm_mock.py`（共享 mock 基础设施）** 同时支持 OpenAI Chat Completions 与 Anthropic Messages API
  - 非流式 JSON / 流式 SSE 自动分派（按请求 body `stream` 字段）
  - 响应队列 + 请求日志：可断言"调了几次 / 每次发了什么"
  - `_connectivity` 探测请求短路（不消耗队列）
- **新增 `tests/test_anthropic_agent.py`（17 项）**
  - 覆盖 non-stream bug 修复（纯文本 / text+tool_use 混响 / 纯 tool_use）
  - 覆盖 stream 回归（纯文本 / text+tool_use 混响）
  - async 路径完整覆盖
  - 公开 API 对齐：pack / get_all_available_tools / 4 个模板管理 builtin_tool
- **新增 `tests/test_base_agent_parity.py`（6 项）**
  - 验证 BaseAgent 同样跑通 mock（非流式 + 流式 + 工具调用）
  - 验证 BaseAgent 的 4 个模板管理 builtin_tool
  - 验证 BaseAgent 与 AnthropicAgent 公开 API 集合一致
- **完整 `pytest tests/` 套件 97/97 通过，无回归**（74 旧 + 23 新）

## [0.3.0] - 2026-07-28

### Added
- **Agent 模板池（`agent_template_pool`）**
  - 新的"模板池"概念：用户注册的 Agent 类**只入池、不实例化、不写入 `agent_list`**
  - 与旧版 `@register_agent`（装饰时立刻实例化 + 写入 `agent_list`）的语义彻底分开
  - 模板的实例化时机由 `activate_template(name)` 显式控制
  - API：
    - `register_template(cls, name, uuid, description, overwrite)` —— 函数式入池
    - `@template_agent(name, uuid, description, overwrite)` —— 装饰器式入池（仅入池，不实例化）
    - `activate_template(name)` —— 把池中 `cls` 实例化并按 `uuid`+`name` 双键写入 `agent_list`
    - `deactivate_template(name)` —— 从 `agent_list` 移除实例，模板仍保留在池中
    - `remove_template(name)` —— 彻底从池中删除（连带从 `agent_list` 移除）
    - `list_templates()` / `get_template(name)` / `is_active(name)` —— 查询
- **`BaseAgent` 新增 4 个 builtin_tool**（让 LLM 在对话中自助管理模板池）
  - `list_templates(name="")` —— 列出/查询模板池
  - `activate_template(name)` —— 显式激活指定模板
  - `deactivate_template(name)` —— 反激活指定模板
  - `register_template(name, description="")` —— 占位说明，提示 LLM "注册 cls 必须在 Python 代码侧完成"
  - 与 `ask_for_help` / `list_agents` / `attempt_completion` / `reload` 一致走 `@builtin_tool` 装饰器，schema 自动从签名推导

### Changed
- **`@register_agent` 标记为弃用**
  - 仍然可用（向后兼容），但调用时通过库内 `logger.warning(...)` 输出迁移提示
  - 推荐迁移路径：`@template_agent(name)` + `activate_template(name)`

### Fixed
- **`Agent_list._ensure_meta` 缺省 `uuid` 不生效** —— 改为 `if not tpl.get("uuid"): tpl["uuid"] = tpl["name"]`，确保从类入参时也能正确补全
- **`BaseAgent.list_templates` 闭包漏 import `agent_list`** —— `NameError`，已在方法体内 `from .Agent_list import agent_list, ...`

### Tests
- **新增 `tests/test_template_pool.py`（33 项）** 覆盖完整模板池 API、装饰器、BaseAgent 4 个 builtin_tool
- 完整 `pytest tests/` 套件 74/74 通过，无回归

## [0.2.2] - 2026-07-21

### Added
- **`dumplingsAI.Agent` 协议无关的工厂基类**
  - 通过类属性 `protocol = "openai" | "anthropic"` 自动选择真实基类
  - 由 `_ProtocolMeta` metaclass 在类创建时替换占位基类，运行时零开销
  - 直接继承 `BaseAgent` / `AnthropicAgent` 的旧写法完全兼容
- **`examples/example7_unified_agent.py`**：演示 3 种写法
  （旧写法 / `Agent` + `protocol` / 动态根据 env 决定协议）

### Changed
- **`AnthropicAgent.api_provider` 默认值去掉**（强制显式设置 endpoint）
  - `_endpoint()` 在 `api_provider` 缺失时抛 `ValueError` 给出明确提示
  - 避免"忘记设置 endpoint 误走到官方 Anthropic API"的隐性 bug
- **全部 `examples/*.py` 中硬编码的 `model_name` 改为 `os.getenv()`**
  - `os.getenv("OPENAI_MODEL")` / `os.getenv("ANTHROPIC_MODEL")`，无 fallback
  - 配套 docstring 同步（`__init__.py` / `anthropic_agent.py` / `llm_transport.py`）

### Fixed
- **`AnthropicAgent` 流式分支漏写 `tool_use` 块**（导致 400 "tool result's tool id not found"）
  - 流式 + 非流式 + 异步非流式 3 处分支都补上 `assistant_blocks.append({"type": "tool_use", ...})`
  - 影响：多 Agent `ask_for_help` 链路不再因 `tool_use_id` 失配而失败
- **`LLMEvent` 缺 `stop_reason` 字段**（导致 `TypeError: unexpected keyword argument 'stop_reason'`）
  - 给 `@dataclass` `LLMEvent` 加 `stop_reason: Optional[str] = None`

## [0.2.1] - 2026-07-20

### Fixed
- `Agent_Base_.py` 内部两处错误的绝对导入 `from Dumplings import agent_list`
  → 改为 `from dumplingsAI import agent_list`（安装后能正常工作）
- `__init__.py` 的 `__version__` 不再硬编码，自动从 `pyproject.toml` 的
  `version` 字段读取（`importlib.metadata`），pyproject 改版本号后无需再
  手动同步 `__init__.py`

### Changed
- `pyproject.toml` 的 `license` 字段从已弃用的 `{ text = "..." }` 表单改为
  SPDX 表达式 `license = "Apache-2.0"`，并移除 deprecated 的
  `License :: OSI Approved :: Apache Software License` classifier
- `AnthropicAgent` 的 class docstring 补充"自定义服务商"小节：
  - 官方 API、第三方代理、完整 URL、OpenAI 兼容网关的 `/anthropic` 子路径、
    AWS Bedrock 等场景
  - 自定义 header（Bearer / 租户 ID）的覆盖方式
  - 完整示例见 `examples/example6_anthropic_custom_provider.py`
- `BaseAgent.__init_subclass__` 增加覆写提示：子类覆写 `pack()` 但未覆写
  `out()` 时给出 warning，引导用户改 `out()` 而非 `pack()`

### Added
- `examples/example6_anthropic_custom_provider.py`：AnthropicAgent 自定义服务商的 4 种用法
- `RELEASING.md`：发布流程文档（PyPI Trusted Publisher 登记、tag 推送、日常发版、并发保护、FAQ）
- `.github/workflows/python-publish.yml` 重写为 **tag 触发自动发布**：
  - `push tags: ['vX.Y.Z', 'vX.Y.ZrcN', 'vX.Y.Z.postN']` 自动 build + publish + 创建 GitHub Release
  - 保留 `workflow_dispatch`（默认 dry_run 不发 PyPI）用于本地验证打包
  - `concurrency` 防止同 tag 重复跑
  - 完整使用 Trusted Publishing（OIDC），无需 API token

## [0.2.0] - 2026-07-19

### Added
- **`http_utils.py`**：基于 httpx 的中央 HTTP 客户端
  - `HTTPClient`（同步）+ `AsyncHTTPClient`（异步）
  - 指数退避 retry（429 / 5xx / 网络错），可配 `max_retries`
  - `timeout` 可单次覆盖
  - 错误分类：抛 `errors.APIError` 子类（`RateLimitError` / `InternalServerError` / `TimeoutError` / `ConnectionError` ...）
- **`errors.py`**：异常类型体系，对齐官方 `openai-python` / `anthropic-sdk-python` 的错误模型
- **`llm_transport.py`**：LLM Transport 抽象层
  - `LLMTransport` 抽象 + `HttpxOpenAITransport` / `HttpxAnthropicTransport` 实现
  - `ChatRequest` / `LLMResponse` / `LLMEvent` / `ToolCall` / `UsageInfo` 中性数据类型
  - Agent 不再直写 HTTP / SSE 解析 / tool_call 抽取；以后换底层（aiohttp / OpenAI SDK）只动一个 transport
- **`tool_runner.py`**：工具执行的 ThreadPoolExecutor
  - `ToolRunner.submit()`：超时返回 `(None, task_id)`，让 LLM 看到 `task_id` 占位继续做别的
  - 自带 `get_status` / `wait` 收割
  - 取代旧版「熔断 N 轮」的长线任务支持
- **`agent_queue.py`**（v0.2 强化）：全局 `AgentQueue`（默认 2 worker，60s idle 退出）
  - `ask_for_help` 改走队列 + 循环检测 + 深度限制
  - 不再因递归栈过深炸出
- **Pydantic 结构化输出**（Phase 2）
  - `@builtin_tool` 新增 `params_model` 参数；自动 `model.model_json_schema()` + `model_validate(args)`
  - 校验失败把错误回灌给 LLM，让它重试
  - `Optional` / 默认值字段不进 `required`
- **异步支持**（Phase 3 起步）
  - `BaseAgent.aconversation_with_tool` / `AnthropicAgent.aconversation_with_tool`
  - 基于 `AsyncHTTPClient` + `transport.achat_stream`
  - `asyncio_mode = "auto"` 开启 pytest 自动识别
- **Token 计数**：新增 `tiktoken>=0.7` 依赖（`token_utils` 计划中的基础）
- **依赖迁移**：`requests` → `httpx`，新增 `pydantic>=2.6`
- **CI**：GH Actions 升级到 `astral-sh/setup-uv@v6`，3.10/3.11/3.12 全绿

### Changed
- `BaseAgent` / `AnthropicAgent.conversation_with_tool` 重构：去掉手写 `requests.post` + SSE 解析，改走 `transport.chat/achat`
- 删除 `max_tool_turns=16` 熔断；改为无熔断循环（长线任务由 `tool_runner` 异步后台支持）
- `tool_timeout: float = 60` + `tool_max_workers: int = 8` 类属性（Agent 自定义超时，默认 60s 兜底）
- `BaseAgent.Connectivity` 走 `HTTPClient`，错误统一抛 `errors.APIError`
- 删除 `AnthropicAgent._call_blocking` / `_call_stream` 死方法（旧 SSE 解析逻辑已搬到 transport）
- README 重写为 PyPI 友好版

### Fixed
- 旧版 GH Actions（pip + flake8 + 无测试）持续失败问题
- 子包名 `dumplings` → `dumplingsAI` 命名不一致（主仓同步更新）
- Pydantic 校验后 `model_dump()` 把默认值也填进去（避免签名里 `**kwargs` 漏 default 报 TypeError）

## [0.1.1] - 2026-07-19

### Added
- `@builtin_tool` 装饰器：内建工具 schema 自动从签名+类型注解+docstring 推导
- `tool_registry.collect_builtin_tools(instance)` 收集器
- `BaseAgent` / `AnthropicAgent` 4 个内建方法（`ask_for_help` / `list_agents` / `attempt_completion` / `reload`）改用 `@builtin_tool` 装饰
- `_builtin_promote_overrides`：子类覆盖 `__init_subclass__` 自动继承 schema
- GH Actions CI（ruff + pytest on 3.10/3.11/3.12）
- PyPI 发布 workflow + Trusted Publishing 配置
- `tests/test_placeholder.py`：包级冒烟测试

### Changed
- 删除硬编码 `builtin_tools` 字典 / `builtin_tools_schema` 列表
- 同步 Anthropic 协议 Agent 重构
- README 重写为 PyPI 友好格式

### Fixed
- 旧版 GH Actions 工作流（`pip + flake8 + 无测试`）持续失败问题
- 子包名 `dumplings` → `dumplingsAI` 命名不一致（主仓同步更新）

## [0.1.0] - 2025-11-24

### Added
- 初始版本：多 Agent 注册、`tool_registry`、XML/FC 双模式工具调用、MCP 桥接、Skill 集成
- `BaseAgent` 抽象基类
- CLI 入口 `main.py`

[Unreleased]: https://github.com/Secret-Dumplings/dumplingsAI/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/Secret-Dumplings/dumplingsAI/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/Secret-Dumplings/dumplingsAI/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Secret-Dumplings/dumplingsAI/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Secret-Dumplings/dumplingsAI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Secret-Dumplings/dumplingsAI/releases/tag/v0.1.0