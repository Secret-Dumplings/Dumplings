---
slug: kb
title: 知识库（Knowledge Base / RAG）
order: 9
icon: DATABASE_OUTLINED
---

# 知识库（Knowledge Base / RAG）

> **v1.0.0+**。让 Agent 回答"基于私有语料"的问题（PDF / DOCX / HTML / Markdown / URL / 扫描件）。

> **v1.1.0+：KB 默认 vendor 在主包**。`pip install tangyuanAI` 自带完整 KB 实现，开箱即用。
> 第三方替换方式见 [plugin-install.md](plugin-install.md)（CLI `install-git` 或 `pip install`）。
>
> ```bash
> pip install tangyuanAI              # 含完整 KB 实现
> # 第三方替换：
> tangyuanai plugin install-git https://github.com/your-fork/kb-alt.git
> ```
>
> 未装第三方时 `tangyuanAI.kb` 自动走 vendored 默认实现。

## 功能一览

- **混合检索**：Qdrant dense（向量）+ sparse（BM25）+ RRF 融合
- **嵌入模型**：远程 HTTP 嵌入端点（任何 OpenAI 兼容 API：包括但不限于 OpenAI、SiliconFlow、阿里云 DashScope、火山引擎等），或本地 sentence-transformers
- **重排模型**：远程 HTTP 重排端点（任何暴露 `/v1/rerank` 的服务），或本地 cross-encoder（sentence-transformers / ColBERT / MonoT5）
- **文档处理**：unstructured（默认）/ minerU（学术 PDF）/ open minerU / Paddle OCR / raw
- **生产级**：嵌入缓存（内存 LRU + 磁盘）、token-aware 批处理、失败重试、模型迁移、持久化

## 快速开始（4 行）

```python
import tangyuanAI as t
from tangyuanAI.kb import EmbedderConfig

t.register_kb("demo", embedder=EmbedderConfig(
    provider="openai", api_base="https://api.openai.com/v1",
    model="text-embedding-3-small", embed_dim=1536))
t.add_document_sync("demo", source="README.md")
results = t.search_sync("demo", "怎么用", top_k=3)
```

> `register_kb/get_kb/search_sync` 是**向后兼容**的全局 API（内部转 `Knowledge` 实例）。**新代码推荐用 `Knowledge` 类**（多实例 + 隔离 + AI 可直接持有对象）。

## Knowledge 类（多实例、隔离、AI 可持有）

`Knowledge` 类 = 单个 KB 实例。可创建多个、完全隔离（独立 Qdrant collection + 独立 meta DB + 独立 id），AI 可直接持有实例调方法。

**用法 1：subclass + 类属性**（模板复用）：
```python
from tangyuanAI.kb import Knowledge, EmbedderConfig

class ResearchKB(Knowledge):
    embedder = EmbedderConfig(provider="openai", api_base="https://api.openai.com/v1",
                              model="text-embedding-3-small", embed_dim=1536)
    doc_processor = "minerU"
    chunk_size = 512
    chunk_overlap = 50

kb1 = ResearchKB("research_2025")   # 同一模板多个实例
kb2 = ResearchKB("research_2026", chunk_size=1024)   # 实例可覆盖类属性
```

**用法 2：直接构造**（无 subclass）：
```python
kb = Knowledge("adhoc", embedder=EmbedderConfig(...),
               doc_processor="unstructured", chunk_size=256)
```

**实例方法（async）**：
```python
doc_ids = await kb.add("paper.pdf")                # 加文档
await kb.add_many(["./a.md", "https://..."], concurrency=8)  # 批量并发
results = await kb.search("向量检索", top_k=5)     # 搜索
docs = await kb.list_documents()                   # 列文档
await kb.migrate(new_embedder_config)              # 模型迁移
tools = kb.register_tools()                        # 注册工具给 Agent
await kb.shutdown()                                # 释放 Qdrant 连接
```

**多实例隔离**：
- 每个实例独立 Qdrant collection（`kb__<name>__<id8>`）+ 独立 meta DB + 独立 id
- `kb1` 和 `kb2` 互不干扰，可同时使用

**`register_kb/get_kb` 全局 API 向后兼容**（返回 `Knowledge` 实例）：`t.register_kb("demo", ...)` / `t.get_kb("demo")` / `t.list_kbs()` / `t.delete_kb("demo")`。

## KB 字段（用户配置）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | str | 必填 | 知识库名称 |
| `embedder` | EmbedderConfig \| None | None | 嵌入模型（None = 不能向量检索） |
| `reranker` | RerankerConfig \| None | None | 重排模型（None = no-op） |
| `top_k` | int | 5 | 请求文档片段数 |
| `doc_processor` | str | unstructured | 文档处理服务商 |
| `chunk_size` | int | 1024 | 分段大小 |
| `chunk_overlap` | int | 200 | 重叠大小 |
| `threshold` | float | 0.0 | 匹配度阈值（仅 rerank 分数生效） |

## 嵌入模型配置

**不硬编码模型列表**。用户指定 provider + api_base + model + embed_dim。

```python
from tangyuanAI.kb import EmbedderConfig

# OpenAI
cfg = EmbedderConfig(
    provider="openai",
    api_base="https://api.openai.com/v1",
    model="text-embedding-3-small",
    embed_dim=1536,               # 必须填（provider 不能探测）
    max_input_tokens=8191,
)

# 本地 Ollama
cfg = EmbedderConfig(
    provider="openai-compatible",
    api_base="http://localhost:11434/v1",
    model="bge-m3",
    embed_dim=1024,
    max_input_tokens=8192,
)
```

**支持 provider**：`openai` / `openai-compatible`（Ollama / vLLM / Xinference / LM Studio / 私网关）/ `cohere` / `voyage` / `jina`。

API key 默认从 `TANGYUAN_<PROVIDER>_API_KEY` 环境变量读；OpenAI-compatible 本地端点无需 key。

## 重排模型配置

```python
from tangyuanAI.kb import RerankerConfig

# Cohere 重排
reranker = RerankerConfig(
    provider="cohere",
    api_base="https://api.cohere.com/v2",
    model="rerank-multilingual-v3.0",
)

# 本地 BGE
reranker = RerankerConfig(
    provider="bge-local",
    model="BAAI/bge-reranker-large",   # 或 model_path="/path/to/model"
)
```

**支持 provider**：`no-op`（默认）/ `openai-compatible` / `cohere` / `jina` / `bge-local` / `colbert` / `monot5`。

## 文档处理服务商

| 名称 | 支持 | 依赖 | 适用 |
|---|---|---|---|
| `unstructured`（默认） | PDF/DOCX/HTML/MD/EPUB/XLSX/CSV/JSON | 内置 | 通用 |
| `minerU` | PDF | `magic-pdf[full]` | 学术论文 / 复杂排版 |
| `openminerU` | PDF/DOCX/PPTX/图片 | 手动装 `openmineru`（未上 PyPI） | 开源 minerU |
| `paddleocr` | PDF/图片 | `paddleocr` | 中文扫描件 |
| `raw` | txt/md/html/json | 内置 | 最轻量 |

按文件扩展名自动派发；`preferred` 参数可强制指定。

## 添加文档

```python
import tangyuanAI as t

# 单个文件 / URL / 目录
t.add_document_sync("demo", "docs/paper.pdf")
t.add_document_sync("demo", "https://example.com/note")
t.add_document_sync("demo", "./docs/")          # 目录递归

# 批量 + 并发
result = t.add_documents_sync("demo", ["a.pdf", "b.md", "https://..."], concurrency=8)
# result = {"success": [doc_ids], "failed": [(source, error)]}

# 内存文本
t.add_document_sync("demo", "raw:note", raw_text="这是内存文本")
```

**去重**：相同内容自动跳过（content-hash）。

## 搜索

```python
results = t.search_sync("demo", "查询文本", top_k=5)

for r in results:
    print(r.score, r.score_type, r.chunk.text)
```

`score_type`：`bm25` / `cosine` / `rrf` / `rerank`。

## 嵌入缓存（生产必备）

重索引成本高，默认启用两级缓存（进程内 LRU 10k 条 + 磁盘 SQLite）。

```python
from tangyuanAI.kb import get_global_cache, NullCache, set_global_cache

get_global_cache().stats()     # {hits, misses, hit_rate, ...}
set_global_cache(NullCache())  # 禁用缓存（调试用）
```

## 模型迁移

切换嵌入模型（自动 re-embed，原子 swap）：

```python
from tangyuanAI.kb import EmbedderConfig, migrate_embedding_model_sync

migrate_embedding_model_sync("demo", EmbedderConfig(
    provider="openai", api_base="https://api.openai.com/v1",
    model="text-embedding-3-large", embed_dim=3072,
))
```

## 工具集成（Agent 调用）

```python
kb = t.get_kb("demo")
names = t.register_kb_tools(kb)   # → ['kb_demo_search', 'kb_demo_list', 'kb_demo_add']
```

Agent 通过 Function Calling 调 `kb_demo_search(query, top_k)`。

## 持久化

- KB 配置 + 文档元数据：`{base_dir}/kb_meta.db`（SQLite WAL）
- 向量数据：Qdrant（embedded 默认在 `{base_dir}/qdrant/`，可切 server）
- 嵌入缓存：`{base_dir}/embed_cache.db`

重启后 `get_kb(name)` 自动恢复；`base_dir` 可用 `TANGYUAN_KB_DIR` 环境变量配置。

## CLI

```bash
# 创建 KB + 添加文档
tangyuanai kb add research \
    --embedder-provider openai --embedder-api-base https://api.openai.com/v1 \
    --embedder-model text-embedding-3-small --embedder-dim 1536 \
    --rerank-provider cohere --rerank-api-base https://api.cohere.com/v2 \
    --rerank-model rerank-multilingual-v3.0 \
    --doc-processor unstructured --source ./papers/*.pdf

# 搜索
tangyuanai kb search research "向量检索" --top-k 5

# 其他
tangyuanai kb list / show <name> / delete <name>
tangyuanai kb migrate <name> --new-embedder-provider X --new-embedder-api-base URL --new-embedder-model Y --new-embedder-dim N
tangyuanai kb providers / processors
tangyuanai kb cache stats / clear
```

## 架构

```
add_document: Loader → DocProcessor → Chunker → Embedder → Qdrant → KBMetaStore
search:       Embedder(query) → Qdrant hybrid (dense+sparse+RRF) → Reranker → threshold

模块拆分（每个可单独替换）：
  kb/loader_*.py     加载（file / url / directory / raw）
  kb/doc_processor_*.py文档处理（unstructured / minerU / openminerU / paddleocr / raw）
  kb/chunker_*.py    切分（recursive / markdown / token / html）
  kb/embedder_*.py   嵌入（openai / cohere / jina / voyage）
  kb/reranker_*.py   重排（noop / openai / cohere / jina / bge / colbert / monot5）
  kb/vector_store.py Qdrant（embedded + server）
  kb/cache.py        嵌入缓存（LRUDisk / Null / 可换 Redis）
  kb/persistence.py  KB 元数据持久化（SQLite / 可换 Postgres）
  kb/{search,ingest,migrate,tool}.py  编排层
```

## 依赖

- **required**：`qdrant-client` / `langchain-text-splitters` / `unstructured` / `openai` / `tenacity` / `msgpack`
- **optional**：`cohere`（embed/rerank）、`sentence-transformers`+`torch`（本地 rerank）、`magic-pdf`（minerU）、`paddleocr`（中文扫描件）

```bash
pip install "tangyuanAI[kb-embed-cohere,kb-rerank-local,kb-processor-mineru,kb-processor-paddleocr]"
```

## 示例

```bash
python -m examples.kb_quickstart
# 用本地 fake embedder 跑通全流程（不连真模型）
```