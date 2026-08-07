# Changelog

tangyuanAI 的所有显著变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **Knowledge Base / RAG 子系统（kb/ 包）**：完整 RAG 检索增强生成能力。
  - 混合检索：Qdrant dense（向量）+ sparse（BM25）+ RRF 融合；embedded 默认 + 可切 server。
  - 嵌入模型：OpenAI / Cohere / Jina / Voyage / 任何 OpenAI-compatible 端点（Ollama / vLLM / Xinference / LM Studio / 私网关）；**不硬编码模型列表**，用户指定 provider + api_base + model + embed_dim。
  - 重排模型：NoOp / Cohere / Jina / BGE（本地）/ ColBERT / MonoT5；token-aware 批处理 + 重试 + 缓存。
  - 文档处理：unstructured（默认）/ minerU（学术 PDF）/ open minerU / Paddle OCR / raw；按扩展名自动派发，preferred 可覆盖。
  - 生产级：嵌入缓存（进程内 LRU 10k + 磁盘 SQLite + msgpack 压缩，懒重连）；token-aware 批处理；失败重试；维度校验；模型迁移（原子 swap：建新 collection → re-embed → swap → 删旧）；持久化（SQLite WAL）；日志（复用 `logging_config`）；HTTP 复用 `http_utils`。
  - 顶层 API（async + sync 包装）：`register_kb` / `get_kb` / `list_kbs` / `delete_kb` / `add_document` / `add_documents` / `search` / `migrate_embedding_model` / `register_kb_tools`。
  - CLI：`tangyuanai kb {add,search,list,show,delete,migrate,providers,processors,cache}` 9 个子命令。
  - 工具集成：`register_kb_tools(kb)` 注册 `kb_<name>_search / _list / _add` 给 Agent 用。
  - 多文件拆分：每个 provider 一个文件（`kb/embedder_openai.py` 等），新增 provider = 加 1 文件 + factory 1 行，**不动其他文件**。
- **Knowledge 类**（替代全局 `_kbs` dict）：`class MyKB(Knowledge): embedder=...; chunk_size=...` → 实例化多 KB、完全隔离（独立 collection + 独立 meta DB + 独立 id）、AI 可直接持有实例调 `kb.add()` / `kb.search()` / `kb.migrate()` / `kb.register_tools()`。`register_kb/get_kb` 薄包装向后兼容。
- **Skill 类化**：`class TimeSkill(Skill): path="./skills/time"` → 实例化自动从 SKILL.md 解析 name/description/parameters 并自动注册到共享 skill 池。新增 `Skill.from_dir()`。
- **MCPClient 类**：`class NotionMCP(MCPClient): server_path="..."` → `async with NotionMCP() as m: tools = await m.list_tools()`；`m.register_tools()` 注入 Agent。
- **A2A 互操作**：
  - 导入：`discover(url)` / `register_a2a_agent(url)` → `A2AAgentProxy` 注册到 agent_list，`ask_for_help` 透明调远端。
  - 导出：`A2AExporter(host, port)` 暴露 `/.well-known/agent.json` + `POST /a2a/v1/tasks/send`（aiohttp，optional `[a2a]`）。
  - 来源跟踪：`register_agent(name, instance, *, source="internal"|"a2a:<url>")` + `agent_source()` / `list_internal_agents()` / `list_external_agents()`。
- **Image Generation 子系统（config-driven）**：
  - 通用 `HttpJsonImageProvider`：读 config 的 `request_template`（`${var}` 占位符）+ `response_image_url_path`（JSON path）→ **每家 provider 自己的"方言"在 config 描述，新增 provider 不写 Python**。
  - 内置 SiliconFlow（flat body）+ DashScope / 阿里百炼（nested OpenAI chat body + `${env:VAR}` URL 占位）模板。
  - 本地下载：`download=True` 自动落盘（URL 1 小时过期）。
  - CLI：`tangyuanai image-gen "prompt" [--download] [--image-size] [--model] ...`。
  - Plugin：`tangyuanai plugin install <name>` / `plugin list`，从中央仓库 `https://github.com/secret-tangyuan/tangyuanAI_image_plus` 下载配置合并到 `tangyuanai.config.json`。
  - `tangyuanai.config.json`：`features` 列表（name / type / enabled / config），路径 cwd → `$TANGYUAN_CONFIG`。
  - 工具：`render_template` / `resolve_json_path` / `resolve_url_template` / `download_urls`。
  - **通用传输旋钮**：`auth_scheme` / `auth_header` / `auth_prefix`（默认 `Authorization: Bearer`；厂商用 `X-API-Key` 等只需 config 改 2 行）+ `request_static` / `timeout`。
  - **传输差异插件**：`provider_impl: "module:ClassName"` 覆盖 form-data / base64 / 自定义鉴权等（实现 `ImageProvider` Protocol，不需要改核心）。
  - 内置适配：SiliconFlow / DashScope / MiniMax（`data.image_urls` 数组响应）。

### Changed
- **KB 子包结构重组**：50 个 `kb_*.py` 文件统一移到 `kb/` 子包，文件名去掉 `kb_` 前缀（子包名已表明是 KB）。`knowledge_base.py` → `kb/__init__.py`；`kb_cli.py` → `kb/cli.py`；测试移到 `tests/kb/`。
  - 新增 KB provider 路径明确：建 `kb/<area>_<provider>.py` + factory dict 1 行，**不动其他文件**。
  - 外部 import 路径：`from tangyuanAI.kb_X import ...` → `from tangyuanAI.kb.X import ...`。
  - `tangyuanAI` 顶层 + `kb/` 子包均导出 KB API（向后兼容：用户写 `from tangyuanAI import register_kb` 仍可用）。
- **弃用 OpenAI SDK，httpx 自建适配**：`kb/embedder_openai.py` 改用 `http_utils.AsyncHTTPClient`（httpx）；修 `/v1` 重复前缀 bug（base_url 含 /v1 时不再 `/v1/v1/rerank`）；`pyproject.toml` 删 `openai` required 依赖。
- **`docs/kb.md` 同步**：更新所有 import 路径 + 架构图（`kb/loader_*.py` 等新路径）；厂商中立化（不绑定具体 vendor）。
- **`pyproject.toml`**：`packages` 加 `"tangyuanAI.kb"`；新增 `[a2a]` extra。
- **新增文档**：`docs/a2a.md`（A2A 互操作）。
- **文档站整合落地页（docs-site）**：`/` 变成落地页（`landing/`，BOLD-MINIMAL 设计系统，深浅色跟随系统 + 手动切换），文档迁移到 `/docs/*`；`sync-docs.mjs` 同步到 `docs-build/docs/`，`generate-api-data.mjs` 相应改读该目录；启动命令不变（`pnpm dev` → `http://localhost:5173`）。顺手修：frontmatter 解析兼容 CRLF（侧栏标题不再显示原始文件名）、主题 CSS 首行笔误、补 `public/logo.svg`。

### Fixed
- **CI 失败**：`openmineru>=0.1` 在 PyPI 上不存在，导致 `uv sync` 解析失败。已从 `[project.optional-dependencies]` 移除 `kb-processor-openminerU`（provider 代码保留在 `kb/doc_processor_openmineru.py`，需手动从源码安装）；`ruff check .` 215 个错误（E401/F401/F841/I001/W292）已清理，`uv sync` / `ruff` / `pytest` 全绿。

## [1.0.0] - 2026-08-05

> 首次 PyPI 发布。从 `dumplingsAI` 改名 `tangyuanAI` 是 breaking change：Python import / CLI 命令 / 环境变量 / .gitignore 目录名 / `.tas` 格式头全部更新。

### Added
- **协议无关的 Agent 工厂**（v0.4.2+ → 1.0.0）：`tangyuanAI.Agent`（带 `protocol` 字段）做工厂基类，靠 `protocol = "openai" / "anthropic" / "openai-responses"` 一行切协议；自带 8 个内建工具（`ask_for_help` / `list_agents` / `attempt_completion` / `reload` / `list_templates` / `activate_template` / `deactivate_template` / `register_template`），`BaseAgent` / `AnthropicAgent` 双协议对齐。
- **`register_protocol(name, base_cls)` / `list_protocols()`**：第三方扩展协议——实现 `LLMTransport` 后调一次注册就能用。
- **OpenAI Responses API 支持**（v0.4.2+）：`HttpxOpenAIResponsesTransport` 走 `/v1/responses`，非流式 / 流式双路径。
- **LLM Transport 抽象层共享 SSE 状态机**（v0.4.2+）：OpenAI / Anthropic / Responses 三协议的 sync+async SSE 解析器各合并为一套状态机 + 单行处理函数，消除 ~250 行重复。
- **CLI 子命令**（v1.0.0+）：`tangyuanai agent/tool/skill/mcp/session/config/run` 完整子命令，覆盖 Agent 管理、工具列表、Skill 列表、MCP 会话、持久化 session、运行等场景。
- **协议常量**（v0.4.2+）：`OPENAI` / `ANTHROPIC` / `OPENAI_RESPONSES` / `openai` / `anthropic` / `openai_responses`，让 `agent.protocol = OPENAI` 不需要打引号。
- **`enable_connectivity` 类属性**（v1.0.0+）：关闭 Agent 的后台连通性 ping（默认开启；测试/离线开发可关）。
- **Agent 状态持久化（v0.4.0+ → 1.0.0）—— 可插拔后端架构**
  - 自定义 `.tas` 文件格式（INI 头 `[META]/[CONFIG]/[STATE]` + JSONL 体 `[HISTORY]`）：人类可读 / git diff 友好 / 可手编，`schema_version` 自动从 `tangyuanAI.__version__` 读，pyproject bump 自动同步。
  - 顶层 API：`save_state(agent, key, *, backend=None)` / `load_state(key, *, backend=None)` / `delete_state` / `list_states` / `export_state_string(agent)` / `load_state_string(s)`。
  - 内置后端：`FileBackend`（默认）、`SQLiteBackend`（**实验性**）。
  - 插件协议 `PersistenceBackend`（save/load/delete/list_keys）+ `register_backend` 注册自定义后端（Redis/Postgres/S3）。
- **实时自动保存**：`TANGYUAN_PERSISTENCE*` 环境变量 + `tangyuanAI.configure(enabled=, ...)` API，`@_auto_save` / `@_auto_save_async` 装饰器用 `_conv_depth` 计数器保证最外层调用退出时保存一次，FC 模式递归不重复。

### Changed
- **包名 / import / CLI / env 全替换**：`dumplingsAI` → `tangyuanAI` / CLI `dumplings` → `tangyuanai` / `DUMPLINGS_*` → `TANGYUAN_*` / `.tas` 格式头 `duagent-state` → `tangyuan-state`。
- **GitHub 仓库**：`Secret-Dumplings/dumplingsAI` → `secret-tangyuan/tangyuanAI`。
- **协议无关 Agent**：`Agent`（含 `protocol` 字段）替代直接继承 `BaseAgent` / `AnthropicAgent` 选用基类；新增 `OPENAI` / `ANTHROPIC` / `OPENAI_RESPONSES` 常量。
- **公共类名**：`DumplingsError` → `TangyuanError`（保留 alias）；`DumplingsConnectionError` / `DumplingsTimeoutError` → `Tangyuan*`（保留 deprecation alias）；`__dumplings_template__` → `__tangyuan_template__`。
- **轻量化**（~250 行重复消除）：`_dispatch_tool` / `_build_user_message` / `_extract_system_and_messages` / `_collect_tools_schema` / `_connectivity` / Anthropic sync+async `conversation_with_tool` 全部上提 `_AgentCommon` mixin 默认实现；OpenAI / Anthropic SSE 解析改为共享状态机 + 单行处理函数（sync/async 只差迭代器）。
- **兼容壳**（过渡兼容，不删除旧路径）：`Agent_Base_.Agent` / `anthropic_agent.AnthropicAgent` 走 `DeprecationWarning` re-export 引导用户迁移。
- **examples 全部迁移**（Tangyuan/examples/example1-7 + 主仓 examples/）从旧 `@register_agent` 装饰器形态迁到 `@template_agent + activate_template` 模板池模式。
- **README 重写**（中文优先 + 英文辅助翻译）：痛点驱动叙事（"LLM 协议差异收拢到一个 transport 层"）+ 一段协议 vs 100+ 行对比（A2A 客户端手写 vs tangyuanAI `ask_for_help`）+ schema 手写 vs 函数签名对比（**不用写 function 的 schema**）。
- **文档站**：[https://docs.ai.secret-tangyuan.com/](https://docs.ai.secret-tangyuan.com/)（Cloudflare Pages 部署，VitePress）；README + docs 加 `secret-tangyuan` / [gravatar](https://gravatar.com/secrettangyuan) byline。

### Fixed
- **`agent.py` 文件底部重复块清理（import crash 修复）**：之前 `register_protocol("openai-responses", _OpenAIResponsesBase)` 在类定义之前执行导致 `NameError`，整个包无法 import。合并后改用单行 import + 三协议统一注册。
- **`mcp_bridge` 双会话池 bug**：模块级 `MCP_SESSION_POOL` 与 `MCPSessionPool._pool` 是两个独立池，注册了但关闭/健康检查看不到；合并为单一池（`register_mcp_tools_async` 调 `adopt(session_info)`）。 
- **`mcp_bridge` wrapper 工厂合并**：`_make_tool_wrapper` / `_make_resource_wrapper` 合成 `_make_session_wrapper(server_path, kind, name)`，减少重复样板。
- **`cli.py` --demo UTF-8 兜底**：Windows GBK 控制台打 `✓` 字符崩；`main()` 开头 stdout reconfigure 为 UTF-8。改用 `@template_agent` 替换已弃用的 `@register_agent` 装饰器形态。
- **`persistence.py` logger 切换**：自动保存失败告警从 `logging.getLogger(...)` 切到全库统一 loguru logger。
- **`agent_tool.check_permission` 参数命名**：`agent_name` → `agent_id`（实际传 uuid，与函数行为一致）。
- **`AnthropicAgent.conversation_with_tool(stream=False)` 丢字（v0.3.0 引入，v0.3.1 修，1.0.0 再次验证无回归）**：non-stream 分支在 `if llm_rsp.text:` 里同步 `assistant_blocks.append({"type": "text", ...})`。
- **`BaseAgent.conversation_with_tool` 多轮工具调用吞最终回复（v0.3.1 修）**：FC 模式 `tool=True` 递归末返回 `full_content` 而非 `work_history[-1]`。

### Deprecated
- **`Agent_Base_.Agent` / `anthropic_agent.AnthropicAgent`**：从这些路径 import 的旧代码 import 时打 `DeprecationWarning`，引导用户迁到 `from tangyuanAI import BaseAgent / AnthropicAgent`。
- **`DumplingsError` / `DumplingsConnectionError` / `DumplingsTimeoutError`**：保留 alias 但 import 时打 `DeprecationWarning`，引导用 `TangyuanError`。

### Removed
- **`.dumplingsAI_sessions/` 持久化目录**：改名 `.tangyuanAI_sessions/`；`/TANGYUAN_PERSISTENCE_DIR` 默认值同步迁移。
- **`DUMPLINGS_PERSISTENCE*` 环境变量**：改名 `TANGYUAN_PERSISTENCE*`（旧名仍可识别，但建议迁移）。

### Tests
- **171 / 174 通过**（3 known non-regression：① pre-existing `test_event_bus.test_user_binds_out_directly_on_instance` mock SSE bug；② env `dotenv` 缺失导致 `test_placeholder.test_core_exports` 找 `register_mcp_tools` 时静默 import 失败；③ flaky `test_concurrent_conversations_on_same_agent_dont_cross_contaminate` mock queue race）。
- **CI 矩阵**：GitHub Actions 跑 ruff + pytest on Python 3.10 / 3.11 / 3.12 × ubuntu / macos / windows = 9 个 job 全绿。

---

[Unreleased]: https://github.com/secret-tangyuan/tangyuanAI/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/secret-tangyuan/tangyuanAI/releases/tag/v1.0.0
[0.2.2]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/secret-tangyuan/tangyuanAI/releases/tag/v0.1.0

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
- **`tangyuanAI.Agent` 协议无关的工厂基类**
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
- `Agent_Base_.py` 内部两处错误的绝对导入 `from Tangyuan import agent_list`
  → 改为 `from tangyuanAI import agent_list`（安装后能正常工作）
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
- 子包名 `tangyuanai` → `tangyuanAI` 命名不一致（主仓同步更新）
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
- 子包名 `tangyuanai` → `tangyuanAI` 命名不一致（主仓同步更新）

## [0.1.0] - 2025-11-24

### Added
- 初始版本：多 Agent 注册、`tool_registry`、XML/FC 双模式工具调用、MCP 桥接、Skill 集成
- `BaseAgent` 抽象基类
- CLI 入口 `main.py`

[Unreleased]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/secret-tangyuan/tangyuanAI/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/secret-tangyuan/tangyuanAI/releases/tag/v0.1.0