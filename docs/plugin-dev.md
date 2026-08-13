---
slug: plugin-dev
title: 插件开发（Plugin / 接口文档）
order: 13
icon: EXTENSION_OUTLINED
---

# 插件开发（Plugin / 接口文档）

> **v1.1.0+**。`tangyuanAI` 核心不再捆绑知识库（RAG）与图片生成实现，改为**插件包**。
> 本页是编写/替换插件的接口文档：核心与插件之间只有两个契约——**插件级契约**（entry point）与**能力级契约**（Python Protocol）。

## 1. 插件架构

```
┌────────────────────────────── tangyuanAI（核心）──────────────────────────────┐
│  agent / tool / mcp / skill / persistence / config / plugin_loader            │
│  CLI：tangyuanai plugin install|list|status                                    │
│  命名空间桥：tangyuanAI.kb / tangyuanAI.imaging（插件没装时给清晰报错）         │
└───────┬──────────────────────────────────────┬────────────────────────────────┘
        │ entry point `tangyuanai.plugins`     │ entry point `tangyuanai.plugins`
        ▼                                      ▼
┌──────────────────────┐          ┌──────────────────────────┐
│ tangyuanai-rag-plus  │          │ tangyuanai-image-plus    │
│ tangyuanAI_rag_plus  │          │ tangyuanAI_image_plus    │
│ type=knowledge_base  │          │ type=image_generation    │
└──────────────────────┘          └──────────────────────────┘
```

- **核心** = 框架 + 插件协议。`pip install tangyuanAI` 只有基础能力。
- **插件** = 独立 pip 包，通过 entry point 注册实现。`pip install "tangyuanAI[all]"` 一次装齐两个官方插件。
- **可替换**：任何第三方包实现同样的 entry point + Protocol，装进环境即替换/新增能力，核心零改动。

## 2. 安装插件

```bash
# 官方两个插件一起装（RAG + Image）
pip install "tangyuanAI[all]"

# 只装某一个
pip install tangyuanai-rag-plus
pip install tangyuanai-image-plus

# 从源码装
pip install git+https://github.com/secret-tangyuan/tangyuanAI_RAG_plus.git
pip install git+https://github.com/secret-tangyuan/tangyuanAI_image_plus.git

# 查看插件状态
tangyuanai plugin status
tangyuanai --doctor
```

插件 config 记录到本地 `tangyuanai.config.json`（可选，离线时用包内置 config）：

```bash
tangyuanai plugin install rag
tangyuanai plugin install image_generation
```

## 3. 插件级契约（entry point）

插件包在 `pyproject.toml` 注册：

```toml
[project.entry-points."tangyuanai.plugins"]
rag = "tangyuanAI_rag_plus.plugin"      # 名字随意，模块路径指向你的 plugin 模块
```

entry point 指向的模块必须暴露（核心用 `importlib.metadata` 发现，惰性导入）：

| 字段 / 方法 | 必填 | 说明 |
|---|---|---|
| `PLUGIN_NAME: str` | ✅ | 插件安装名，如 `"rag"` / `"image"` |
| `PLUGIN_TYPE: str` | ✅ | `knowledge_base` → 桥接 `tangyuanAI.kb`；`image_generation` → 桥接 `tangyuanAI.imaging`；其它类型可自定义（不桥接，仅 CLI/发现）。A2A 是核心原生能力，不属于任何插件 |
| `PLUGIN_TITLE: str` | ✅ | 展示名 |
| `PLUGIN_DESCRIPTION: str` | ✅ | 一句话说明 |
| `PLUGIN_CONFIGS: list[dict]` | ✅ | 内置 feature config（`tangyuanai plugin install` 离线用；与 `tangyuanai.config.json` 的 feature schema 一致） |
| `get_api() -> ModuleType` | ⭕ | 返回公开 API 模块（默认返回插件模块自身） |
| `add_cli_subparsers(subparsers)` | ⭕ | 注册 CLI 子命令 |
| `check() -> (bool, str)` | ⭕ | 环境自检 |

**命名空间桥接**：`PLUGIN_TYPE="knowledge_base"` 时，核心把 `get_api()` 返回的模块树
别名注册到 `tangyuanAI.kb`（含子模块，`from tangyuanAI.kb.config import X` 也生效）；
`image_generation` 同理桥接到 `tangyuanAI.imaging`。未装插件时这两个命名空间可导入，
但取 API 会抛出带安装提示的 `ImportError`。

**多个同类型插件**：按 entry point 名排序，**名字靠后者覆盖前者**（`tangyuanAI.kb` 指向最后加载的插件）。

### 最小可替换插件示例

```python
# my_kb_plugin/plugin.py
PLUGIN_NAME = "my-kb"
PLUGIN_TYPE = "knowledge_base"   # 桥接到 tangyuanAI.kb
PLUGIN_TITLE = "My KB"
PLUGIN_DESCRIPTION = "第三方知识库实现"
PLUGIN_CONFIGS = [{"name": "my-kb", "type": "knowledge_base", "enabled": True, "config": {}}]

def get_api():
    import my_kb_plugin.api as api
    return api

def add_cli_subparsers(subparsers):
    from my_kb_plugin.cli import add_subparser
    add_subparser(subparsers)
```

```toml
[project.entry-points."tangyuanai.plugins"]
my-kb = "my_kb_plugin.plugin"
```

`pip install .` 后 `tangyuanAI.kb.*` 就是你的实现了。

## 4. 能力级契约（图片插件）

`ImageProvider` 是结构化子类型（Protocol，鸭子类型，无需继承）：

```python
class ImageProvider(Protocol):
    name: str
    async def generate(self, *, prompt: str, model: str | None = None, **kwargs) -> list[str]: ...
    async def close(self) -> None: ...
```

- **通用 HTTP JSON 厂商**：零代码——复制 `image_generation.json` 改 `request_template` / `response_image_url_path` / `api_key_env` 即可（config 驱动）。
- **协议特殊**（form-data / base64 / 动态签名）：实现 `ImageProvider`，config 里写 `provider_impl: "module:ClassName"`。核心按 `module:ClassName` 导入并实例化 `cls(name=..., feature_cfg=...)`。

### 图片 feature config schema

```json
{
  "name": "image_generation",
  "type": "image_generation",
  "enabled": true,
  "config": {
    "provider": "siliconflow",
    "api_base": "https://api.siliconflow.cn/v1/images/generations",
    "api_key_env": "TANGYUAN_IMAGE_API_KEY",
    "default_model": "Qwen/Qwen-Image-Edit-2509",
    "request_template": { "model": "${model}", "prompt": "${prompt}" },
    "request_static": { "stream": false },
    "response_image_url_path": "data.0.url"
  }
}
```

`${var}` 占位符从 `ImageGenerator.generate(prompt=..., model=..., **kwargs)` 填充；`${env:VAR}` 从环境变量填充。

## 5. 能力级契约（RAG 插件）

KB 内部能力全部是 Protocol（`tangyuanAI_rag_plus/protocols.py`），满足方法签名即可替换：

| 能力 | Protocol | 关键方法 |
|---|---|---|
| 嵌入 | `Embedder` | `async embed(text)` / `async embed_batch(texts)` / `async close()` |
| 重排 | `Reranker` | `async rerank(query, chunks, top_k) -> list[(Chunk, float)]` |
| 向量库 | `VectorStore` | `async create_collection / upsert / search / delete / scroll / close` |
| 切分 | `Chunker` | `split(text, meta) -> list[Chunk]` |
| 文档处理 | `DocProcessor` | `can_handle(path)` / `process(path) -> list[Document]` |
| 加载 | `Loader` | `can_handle(source)` / `load(source) -> list[Document]` |
| 缓存 | `EmbeddingCache` | `async get / set / clear` / `stats()` |

注册自定义 provider（示例，嵌入模型）：

```python
import tangyuanAI_rag_plus.embedder_factory as ef

class MyEmbedder:
    name = "my-embedder"
    dim = 768
    async def embed(self, text): ...
    async def embed_batch(self, texts): ...
    async def close(self): ...

ef._EMBEDDERS["my-embedder"] = MyEmbedder
# 之后 register_kb(embedder=EmbedderConfig(provider="my-embedder", ...))
```

同理：`reranker_factory._RERANKERS` / `chunker_factory._CHUNKERS` / `loader_factory._LOADERS` / `doc_processor_factory._PROCESSORS`。
数据模型 `Chunk` / `Document` / `SearchResult` / `KnowledgeBase` 等见 `tangyuanAI_rag_plus/types.py`（pydantic 字段即契约）。

## 6. 中央 config 仓库（发布新厂商配置）

`tangyuanai plugin install <name>` 默认从中央仓库下载 `<name>.json`：

- 图片：https://github.com/secret-tangyuan/tangyuanAI_image_plus（每个 provider 一个 `<name>.json`）
- RAG：https://github.com/secret-tangyuan/tangyuanAI_RAG_plus（`rag.json` 清单）

发布新厂商配置 = 往中央仓库加一个 `<name>.json`（或同步进插件包 `PLUGIN_CONFIGS`），
用户 `tangyuanai plugin install <name> --repo <repo>` 即用。

已知插件名 → 仓库自动匹配（`plugin_store.PLUGIN_REPO_MAP`），无需 `--repo`。

## 7. 迁移指南（v1.0.x → v1.1.0）

- `tangyuanAI.kb` / `tangyuanAI.imaging` 命名空间不变；`import tangyuanAI` 用法不变。
- KB / 图片实现移到插件包；重依赖（qdrant / unstructured / torch 等）不再随核心安装。
- 核心的 `kb-*` 可选依赖 extras 迁移到 `tangyuanai-rag-plus` 的 extras（`kb-embed-cohere` 等）。
- A2A 保持核心原生（`tangyuanAI.a2a_*`），不随插件迁移；导出需要 `pip install "tangyuanAI[a2a]"`。
- 升级：`pip install --upgrade "tangyuanAI[all]"`。
