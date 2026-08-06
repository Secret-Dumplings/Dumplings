# -*- coding: utf-8 -*-
"""
Knowledge Base 快速上手（examples/kb_quickstart.py）
====================================================

**零外部 API 也能跑**：用本地 Ollama（openai-compatible）或直接跑 demo。

用法：
    python -m examples.kb_quickstart

或指定真实 embedding 端点：
    python -m examples.kb_quickstart openai https://api.openai.com/v1 text-embedding-3-small 1536

不指定 → 用本地 fake embedder 演示（不连真模型）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _fake_embedder_dim(texts):
    """演示用 fake embedder（不连真模型）。"""
    from tangyuanAI.kb_embedder_base import BaseEmbedder
    from tangyuanAI.kb_config import EmbedderConfig

    class _Fake(BaseEmbedder):
        client_name = "fake"

        def _init_client(self):
            return object()

        async def _embed_one_batch(self, batch):
            import hashlib
            out = []
            for t in batch:
                h = hashlib.sha256(t.encode()).digest()
                vec = [h[i] / 255.0 for i in range(min(self.dim, len(h)))]
                while len(vec) < self.dim:
                    vec.append(0.0)
                out.append(vec)
            return out

    # 注册到 factory
    import tangyuanAI.kb_embedder_factory as factory
    factory._EMBEDDERS["openai-compatible"] = _Fake

    return EmbedderConfig(
        provider="openai-compatible", api_base="http://fake",
        model="fake", embed_dim=16, max_input_tokens=1000, batch_size=10,
    )


def main() -> int:
    import tangyuanAI as t

    # 用 tmp 目录隔离（不污染仓库）
    base_dir = tempfile.mkdtemp(prefix="kb_demo_")
    os.environ["TANGYUAN_KB_DIR"] = base_dir

    # --- 1. 选 embedding 配置 ---
    if len(sys.argv) >= 5:
        # 真实端点：python kb_quickstart.py <provider> <api_base> <model> <dim>
        embedder = t.EmbedderConfig(
            provider=sys.argv[1], api_base=sys.argv[2],
            model=sys.argv[3], embed_dim=int(sys.argv[4]),
        )
    else:
        print("未指定 embedder → 用本地 fake embedder 演示（不连真模型）。")
        embedder = _fake_embedder_dim(None)

    # --- 2. 创建 KB ---
    kb = t.register_kb(
        name="quickstart",
        embedder=embedder,
        doc_processor="raw",          # txt/md 直接读
        chunk_size=200, chunk_overlap=20,
        top_k=3, threshold=0.0,
        base_dir=base_dir,
        qdrant_location=f"{base_dir}/qdrant",
    )
    print(f"KB 创建成功: {kb.name}")

    # --- 3. 添加文档 ---
    doc = "# tangyuanAI 知识库\n\nKnowledge Base 子系统支持全文检索 + 向量检索 + 重排。\n"
    doc += "它基于 Qdrant 向量库，支持 OpenAI / Ollama / vLLM 等嵌入模型。\n"
    doc += "支持 PDF / DOCX / Markdown / URL 等文档格式。\n"
    t.add_document_sync("quickstart", "raw:quickstart", raw_text=doc)

    md_file = Path(base_dir) / "example.md"
    md_file.write_text(
        "# 示例\n\nPython 多智能体协作框架，让 LLM 像公司团队一样分工。\n",
        encoding="utf-8",
    )
    t.add_document_sync("quickstart", str(md_file))

    # --- 4. 搜索 ---
    print("\n搜索结果:")
    for query in ["向量检索", "Qdrant", "智能体"]:
        results = t.search_sync("quickstart", query, top_k=3)
        print(f"\n  查询: {query}")
        for r in results:
            snippet = r.chunk.text[:80].replace("\n", " ")
            print(f"    [{r.rank + 1}] ({r.score_type.value}, {r.score:.3f}) {snippet}")

    # --- 5. 工具桥接（可选）---
    names = t.register_kb_tools(kb)
    print(f"\n已注册 Agent 工具: {names}")

    # --- 6. 列出 KB ---
    print(f"\n所有 KB: {[k.name for k in t.list_kbs()]}")

    # --- 7. 关闭 Qdrant 连接（应用退出前调用，避免资源泄漏）---
    t.shutdown_kb()

    print("\n完成。清理: 直接删除临时目录即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())