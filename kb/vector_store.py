# -*- coding: utf-8 -*-
"""
Qdrant VectorStore（kb_vector_store.py）
========================================

**职责**：Qdrant 向量库实现（embedded + server 双模式）。

**模式**：
- embedded：`location="./.tangyuanAI_kbs/qdrant"`（in-process Rust 核心，零运维）
- server：`url="https://qdrant.prod.example.com"` + `api_key`（多进程 / 分布式）

**检索**：
- dense-only（默认）：HNSW 余弦
- hybrid（`enable_sparse=True`）：dense + BM25 sparse + RRF fusion

**复用**：
- `..kb_sparse.Bm25SparseVectorizer`（sparse 向量化器，可替换）
- `..logging_config.get_logger`

**可替换**：换 Milvus / Weaviate = 实现 `kb_vector_store_base.BaseVectorStore` 同名接口。
"""
from __future__ import annotations

from typing import Any

from tangyuanAI.logging_config import get_logger

from .sparse import Bm25SparseVectorizer, SparseVector

__all__ = ["QdrantVectorStore"]


def _is_valid_uuid(s: str) -> bool:
    """判断字符串是否是合法 UUID（含 32 位 hex 无横线形式）。"""
    import uuid as _uuid
    try:
        _uuid.UUID(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


_logger = get_logger("kb.vectorstore.qdrant")


class QdrantVectorStore:
    """Qdrant 向量库。"""
    name = "qdrant"

    def __init__(
        self,
        *,
        location: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        prefer_grpc: bool = True,
        timeout: float = 30.0,
        enable_sparse: bool = False,
        enable_quantization: bool = True,
    ):
        from qdrant_client import QdrantClient, models

        self._models = models
        self.enable_sparse = enable_sparse
        self.enable_quantization = enable_quantization
        self._sparse_vec: Bm25SparseVectorizer | None = None
        self._collections: dict[str, int] = {}  # name -> dim

        if url:
            self._client = QdrantClient(
                url=url,
                api_key=api_key,
                prefer_grpc=prefer_grpc,
                timeout=timeout,
            )
            _logger.info(f"QdrantVectorStore connected to server: {url}")
        else:
            # embedded 模式
            self._client = QdrantClient(
                path=location or ":memory:",
                prefer_grpc=False,
                timeout=timeout,
            )
            _logger.info(f"QdrantVectorStore embedded: {location or ':memory:'}")

        self._get_sparse_vec() if enable_sparse else None

    def _get_sparse_vec(self) -> Bm25SparseVectorizer:
        if self._sparse_vec is None:
            self._sparse_vec = Bm25SparseVectorizer()
        return self._sparse_vec

    # === collection ===

    async def create_collection(
        self,
        name: str,
        dim: int,
        *,
        distance: str = "Cosine",
        enable_quantization: bool = True,
        **kwargs: Any,
    ) -> None:
        models = self._models
        existing = self._client.collection_exists(name)
        if existing:
            info = self._client.get_collection(name)
            vectors_cfg = info.config.params.vectors
            if isinstance(vectors_cfg, dict):
                # 命名向量：取 dense
                dense_cfg = vectors_cfg.get("dense") or next(iter(vectors_cfg.values()), None)
                existing_dim = dense_cfg.size if dense_cfg else None
            else:
                existing_dim = vectors_cfg.size
            if existing_dim is not None and existing_dim != dim:
                raise ValueError(
                    f"collection {name!r} already exists with dim {existing_dim}, "
                    f"requested {dim}. Delete it first (delete_kb) or use migrate_embedding_model."
                )
            self._collections[name] = dim
            return

        # dense vector config
        hnsw = dict(
            m=16,
            ef_construct=100,
            full_scan_threshold=10000,
        )
        vector_params = models.VectorParams(
            size=dim,
            distance=getattr(models.Distance, distance.upper(), models.Distance.COSINE),
            hnsw_config=models.HnswConfigDiff(**hnsw),
        )

        sparse_config: dict | None = None
        if self.enable_sparse:
            sparse_config = models.SparseVectorParams(
                modifier=models.Modifier.IDF  # type: ignore[attr-defined]
            )

        quantization = None
        if enable_quantization and self.enable_quantization:
            quantization = models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8,
                    quantile=0.99,
                    always_ram=True,
                )
            )

        if self.enable_sparse:
            # 命名向量：dense + sparse
            vectors_config: Any = {"dense": vector_params}
        else:
            vectors_config = vector_params

        self._client.create_collection(
            collection_name=name,
            vectors_config=vectors_config,
            sparse_vectors_config={"sparse": sparse_config} if sparse_config else None,
            optimizers_config=models.OptimizersConfigDiff(
                default_segment_number=4,
                indexing_threshold=20000,
            ),
            quantization_config=quantization,
        )
        self._collections[name] = dim
        _logger.info(f"collection created: {name} dim={dim} sparse={bool(sparse_config)} quant={bool(quantization)}")

    # === upsert ===

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        if len({len(ids), len(vectors), len(payloads)}) != 1:
            raise ValueError("ids / vectors / payloads must have same length")
        models = self._models

        # sparse（可选）
        sparse_vecs: list[SparseVector] | None = None
        if self.enable_sparse:
            sv = self._get_sparse_vec()
            # 增量 fit：用这批 text 更新 vocab + IDF
            sv.fit(p["text"] for p in payloads)
            sparse_vecs = [sv.encode(p.get("text", "")) for p in payloads]

        points = []
        for i, (pid, vec, payload) in enumerate(zip(ids, vectors, payloads)):
            if sparse_vecs is not None:
                sp = sparse_vecs[i]
                vector = {
                    "dense": vec,
                    "sparse": models.SparseVector(
                        indices=sp.indices, values=sp.values
                    ),
                }
            else:
                vector = vec
            points.append(models.PointStruct(
                id=self._as_point_id(pid),
                vector=vector,
                payload=payload,
            ))

        # 分批 upsert（Qdrant 单次上限 ~1024 点）
        batch_size = 512
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=collection,
                points=points[i:i + batch_size],
                wait=True,
            )

    # === search ===

    async def search(
        self,
        collection: str,
        query_vec: list[float],
        query_text: str,
        top_k: int,
        *,
        filter_: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        models = self._models
        qfilter = self._build_filter(filter_) if filter_ else None

        if self.enable_sparse and self._sparse_vec is not None and self._sparse_vec.n_docs() > 0:
            # Hybrid：dense + sparse + RRF
            query_sparse = self._sparse_vec.encode(query_text)
            over_fetch = min(top_k * 5, 200)
            result = self._client.query_points(
                collection_name=collection,
                prefetch=[
                    models.Prefetch(
                        query=models.NearestQuery(nearest=query_vec),
                        using="dense",
                        limit=over_fetch,
                        filter=qfilter,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=query_sparse.indices,
                            values=query_sparse.values,
                        ),
                        using="sparse",
                        limit=over_fetch,
                        filter=qfilter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        else:
            # Dense-only（未启用 sparse 或 sparse 还没数据）
            if self.enable_sparse:
                # 命名向量模式：用 dense
                result = self._client.query_points(
                    collection_name=collection,
                    query=models.NearestQuery(nearest=query_vec),
                    using="dense",
                    limit=top_k,
                    query_filter=qfilter,
                    with_payload=True,
                    with_vectors=False,
                    search_params=models.SearchParams(hnsw_ef=128, exact=False),
                )
            else:
                result = self._client.query_points(
                    collection_name=collection,
                    query=models.NearestQuery(nearest=query_vec),
                    limit=top_k,
                    query_filter=qfilter,
                    with_payload=True,
                    with_vectors=False,
                    search_params=models.SearchParams(hnsw_ef=128, exact=False),
                )

        out: list[tuple[str, float, dict[str, Any]]] = []
        for point in result.points:
            payload = dict(point.payload or {})
            out.append((str(point.id), float(point.score), payload))
        return out

    # === delete ===

    async def delete(self, collection: str, ids: list[str]) -> None:
        if not ids:
            return
        models = self._models
        for i in range(0, len(ids), 512):
            self._client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(
                    points=[self._as_point_id(pid) for pid in ids[i:i + 512]]
                ),
                wait=True,
            )

    async def drop_collection(self, collection: str) -> None:
        """彻底删除 collection（迁移后清理用）。"""
        try:
            self._client.delete_collection(collection_name=collection)
            _logger.info(f"collection dropped: {collection}")
        except Exception as e:
            _logger.warning(f"drop collection {collection!r} failed: {e}")

    # === scroll ===

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filter_: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        records, next_offset = self._client.scroll(
            collection_name=collection,
            limit=limit,
            offset=offset,
            scroll_filter=self._build_filter(filter_) if filter_ else None,
            with_payload=True,
            with_vectors=False,
        )
        points = [dict(r.payload or {}, **{"_id": str(r.id)}) for r in records]
        return points, next_offset

    async def close(self) -> None:
        try:
            self._client.close()
        except Exception as e:
            _logger.debug(f"qdrant close: {e}")

    # === 工具 ===

    @staticmethod
    def _build_filter(f: dict[str, Any]) -> Any:
        """把简单 filter dict 转成 Qdrant Filter。

        支持格式：
        - {"visibility": "public"}              → 等值
        - {"visibility": {"$in": ["a", "b"]}}  → in
        - {"$must": [...], "$must_not": [...]} → 组合
        """
        from qdrant_client import models

        def _cond(key: str, val: Any):
            if isinstance(val, dict):
                if "$in" in val:
                    return models.FieldCondition(key=key, match=models.MatchAny(any=val["$in"]))
                if "$gte" in val:
                    return models.FieldCondition(key=key, range=models.Range(gte=val["$gte"]))
                if "$lte" in val:
                    return models.FieldCondition(key=key, range=models.Range(lte=val["$lte"]))
                raise ValueError(f"unsupported filter operator: {list(val)}")
            return models.FieldCondition(key=key, match=models.MatchValue(value=val))

        if "$must" in f or "$must_not" in f:
            must = [models.Filter(must=[_cond(k, v) for k, v in f["$must"].items()])] if f.get("$must") else None
            must_not = [models.Filter(must_not=[_cond(k, v) for k, v in f["$must_not"].items()])] if f.get("$must_not") else None
            return models.Filter(must=must, must_not=must_not)

        return models.Filter(must=[_cond(k, v) for k, v in f.items()])

    @staticmethod
    def _as_point_id(pid: str) -> Any:
        """把字符串 id 转成 Qdrant 接受的 point id。

        Qdrant 接受 UUID 或整数。我们的 chunk.id 是 uuid4 hex（32 位，无横线）→ 合法 UUID。
        用户传入任意字符串时 → 确定性 uuid5，保证幂等。
        """
        import uuid as _uuid
        if _is_valid_uuid(pid):
            return pid
        # 确定性映射：同一字符串 → 同一 UUID
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"kb:{pid}"))

    def collection_names(self) -> list[str]:
        return self._client.get_collections().collections

    def __repr__(self) -> str:
        return f"QdrantVectorStore(name={self.name}, sparse={self.enable_sparse})"
