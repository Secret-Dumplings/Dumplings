# -*- coding: utf-8 -*-
"""
Sparse 向量化器（kb_sparse.py）
================================

**职责**：把文本转成 Qdrant SparseVector（indices + values），用于混合检索（dense + sparse + RRF）。

**为什么需要**：Qdrant 的 sparse vector 不会自动从文本生成；需要我们自己算 term 权重。
这里提供 BM25 风格的实现（term frequency + inverse document frequency）。

**可替换**：将来要换 SPLADE / 学习式 sparse 模型，实现同名接口即可。

**分层**：
- `kb_sparse.py`（本文件）：稀疏向量化器
- `kb_vector_store.py`：用它做 hybrid upsert / search
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from pydantic import BaseModel, Field


__all__ = ["Bm25SparseVectorizer", "SparseVectorizer"]


# ---------------------------------------------------------------------------
# Sparse 向量数据结构
# ---------------------------------------------------------------------------

class SparseVector(BaseModel):
    """Qdrant SparseVector 等价物。"""
    indices: list[int] = Field(..., description="term 在 vocab 里的 index（升序）")
    values: list[float] = Field(..., description="对应权重")

    def __init__(self, **data):
        super().__init__(**data)
        # 保持 indices 升序（Qdrant 要求）
        pairs = sorted(zip(self.indices, self.values))
        object.__setattr__(self, "indices", [p[0] for p in pairs])
        object.__setattr__(self, "values", [p[1] for p in pairs])


# ---------------------------------------------------------------------------
# 分词器
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """基础英文 + 数字分词（中文按字切）。"""
    # 英文 token
    en = [t.lower() for t in _TOKEN_RE.findall(text)]
    # 中文：按单字（简单起见；专业中文分词可换成 jieba）
    zh = [c for c in text if "一" <= c <= "鿿"]
    return en + zh


# ---------------------------------------------------------------------------
# BM25 sparse vectorizer
# ---------------------------------------------------------------------------

class SparseVectorizer:
    """协议占位：任何文本 → SparseVector。"""

    def fit(self, texts: Iterable[str]) -> None:
        """用一批文本建立 vocab + IDF。"""
        ...

    def encode(self, text: str) -> SparseVector:
        ...

    def vocab_size(self) -> int:
        ...


class Bm25SparseVectorizer(SparseVectorizer):
    """BM25 风格 sparse vectorizer。

    - fit(docs)：统计文档频率（DF）+ IDF
    - encode(text)：TF * IDF 权重
    """
    def __init__(self, *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._n_docs: int = 0

    # === fit ===

    def fit(self, texts: Iterable[str]) -> None:
        """建立 vocab + IDF + 平均文档长度。"""
        doc_freq: Counter[str] = Counter()
        total_len = 0
        n_docs = 0

        for text in texts:
            terms = _tokenize(text)
            if not terms:
                continue
            # 每文档每 term 计 1 次（DF 定义）
            doc_freq.update(set(terms))
            total_len += len(terms)
            n_docs += 1

        if n_docs == 0:
            return

        self._n_docs = n_docs
        self._avg_dl = total_len / n_docs
        self._vocab = {term: i for i, term in enumerate(sorted(doc_freq.keys()))}
        self._idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    # === encode ===

    def encode(self, text: str) -> SparseVector:
        if not self._vocab:
            raise RuntimeError("Bm25SparseVectorizer.fit() must be called before encode()")
        terms = _tokenize(text)
        if not terms:
            return SparseVector(indices=[], values=[])

        tf: Counter[str] = Counter(terms)
        dl = len(terms)
        norm = max(1.0, math.sqrt(dl))  # 长度归一

        entries: dict[int, float] = {}
        for term, count in tf.items():
            idx = self._vocab.get(term)
            if idx is None:
                continue
            idf = self._idf.get(term, 0.0)
            if idf <= 0:
                continue
            # BM25 TF 变换
            tf_frac = count * (self.k1 + 1) / (
                count + self.k1 * (1 - self.b + self.b * dl / self._avg_dl)
            )
            entries[idx] = (tf_frac * idf) / norm

        if not entries:
            return SparseVector(indices=[], values=[])
        return SparseVector(indices=sorted(entries), values=[entries[i] for i in sorted(entries)])

    # === 维护 ===

    def vocab_size(self) -> int:
        return len(self._vocab)

    def n_docs(self) -> int:
        return self._n_docs

    def __repr__(self) -> str:
        return f"Bm25SparseVectorizer(vocab={len(self._vocab)}, docs={self._n_docs})"