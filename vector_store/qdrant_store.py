"""Qdrant 向量存储实现。"""

from __future__ import annotations

import threading
import uuid
from contextlib import nullcontext
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance
from qdrant_client.models import FieldCondition
from qdrant_client.models import Filter
from qdrant_client.models import MatchValue
from qdrant_client.models import PointStruct
from qdrant_client.models import VectorParams

from models import Embedding
from models import IndexChunk
from vector_store.base import BaseVectorStore
from vector_store.base import SearchResult
from vector_store.qdrant_config import load_qdrant_config
from vector_store.qdrant_config import QdrantConfig


_DISTANCE_MAP = {
    "cosine": Distance.COSINE,
    "euclidean": Distance.EUCLID,
    "dot": Distance.DOT,
}

# Qdrant 远程模式默认单请求 payload 上限 32MB，分批写入避免 400 Payload error
_DEFAULT_UPSERT_BATCH_SIZE = 100


def _make_point_id(document_id: str, chunk_id: int) -> str:
    """生成确定性 UUID 作为 Qdrant point id。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_{chunk_id}"))


def _make_mini_point_id(document_id: str, chunk_id: int, mini_idx: int) -> str:
    """生成 mini-chunk 的确定性 UUID。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"mini_{document_id}_{chunk_id}_{mini_idx}"))


class QdrantVectorStore(BaseVectorStore):
    """基于 Qdrant 的向量存储实现。

    支持本地模式（文件存储）和远程模式（Qdrant 服务器）。
    """

    # 类级锁：_ensure_collection 的 check-then-act 防并行首写竞态
    _ensure_lock = threading.Lock()
    # 本地模式 upsert 串行锁（SQLite 不支持并发写；远程模式不加锁）
    _local_upsert_lock = threading.Lock()

    def __init__(self, config: QdrantConfig | None = None) -> None:
        self.config = config or load_qdrant_config()
        self._client = self._create_client()

    def _create_client(self) -> QdrantClient:
        if self.config.mode == "local":
            path = self.config.path or "./qdrant_data"
            return QdrantClient(path=path)
        return QdrantClient(
            host=self.config.host or "localhost",
            port=self.config.port or 6333,
            grpc_port=self.config.grpc_port,
            api_key=self.config.api_key,
            https=self.config.https,
        )

    # ------------------------------------------------------------------ #
    # BaseVectorStore 接口实现
    # ------------------------------------------------------------------ #

    @property
    def collection_name(self) -> str:
        return self.config.collection_name

    def collection_exists(self) -> bool:
        collections = self._client.get_collections().collections
        return any(c.name == self.collection_name for c in collections)

    def create_collection(self, dimension: int) -> None:
        distance = _DISTANCE_MAP.get(self.config.distance, Distance.COSINE)
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=dimension, distance=distance),
        )

    def _ensure_collection(self, dimension: int) -> None:
        """如果 Collection 不存在且配置允许自动创建，则创建之（类级锁防竞态）。"""
        with self._ensure_lock:
            if not self.collection_exists() and self.config.auto_create_collection:
                self.create_collection(dimension)
                self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        """创建 payload 关键字索引供关键词兜底检索。

        创建以下索引：
          - keywords (keyword)  — 精确匹配标注词
          - data_types (keyword) — 按类型筛选
          - content (text)       — 全文索引兜底匹配
        """
        index_fields = [
            ("keywords", "keyword"),
            ("data_types", "keyword"),
            ("content", "text"),
        ]
        for field_name, field_schema in index_fields:
            try:
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )
            except Exception:
                pass  # 索引已存在，忽略

    def upsert_chunks(self, chunks: list[IndexChunk]) -> None:
        if not chunks:
            return

        # 从第一个 chunk 推断向量维度
        first = chunks[0]
        dim = len(first.embeddings.full_embedding) if first.embeddings.full_embedding else 0
        if dim == 0:
            return

        self._ensure_collection(dim)

        points: list[PointStruct] = []
        for chunk in chunks:
            if not chunk.embeddings.full_embedding:
                continue

            # 1. 主 chunk point（标准 chunk 或 large chunk）
            point_id = _make_point_id(chunk.source_document.id, chunk.chunk_id)
            payload: dict[str, Any] = {
                "document_id": chunk.source_document.id,
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "blurb": chunk.blurb,
                "section_type": chunk.section_type.value,
                "title": chunk.source_document.title,
                "is_large_chunk": chunk.is_large_chunk,
                "chunk_level": chunk.chunk_level,
                "large_chunk_reference_ids": chunk.large_chunk_reference_ids,
                "large_chunk_id": chunk.large_chunk_id,
                "doc_summary": chunk.doc_summary,
                "chunk_context": chunk.chunk_context,
                "mini_chunk_count": len(chunk.mini_chunk_texts) if chunk.mini_chunk_texts else 0,
                "mini_chunk_texts": chunk.mini_chunk_texts or [],
                "mini_chunk_offsets": chunk.mini_chunk_offsets or [],
                "is_mini_chunk": False,
                "image_file_id": chunk.image_file_id,
                "keywords": [],       # BGE 富化: 语义标注关键词
                "data_types": [],     # BGE 富化: 数据类型标签
            }
            if chunk.title_embedding:
                payload["title_embedding"] = chunk.title_embedding
            if chunk.embeddings.mini_chunk_embeddings:
                payload["mini_chunk_embeddings"] = chunk.embeddings.mini_chunk_embeddings

            # 合并自定义 payload（日志模式库等结构化数据使用）
            if chunk.custom_payload:
                payload.update(chunk.custom_payload)

            points.append(
                PointStruct(
                    id=point_id,
                    vector=chunk.embeddings.full_embedding,
                    payload=payload,
                )
            )

            # 2. 为每个 mini-chunk 创建独立的 point（支持 mini-chunk 向量搜索）
            if chunk.embeddings.mini_chunk_embeddings and chunk.mini_chunk_texts:
                for mini_idx, (mini_emb, mini_text) in enumerate(
                    zip(chunk.embeddings.mini_chunk_embeddings, chunk.mini_chunk_texts)
                ):
                    if not mini_emb:
                        continue
                    mini_point_id = _make_mini_point_id(
                        chunk.source_document.id, chunk.chunk_id, mini_idx
                    )
                    mini_payload: dict[str, Any] = {
                        "document_id": chunk.source_document.id,
                        "chunk_id": chunk.chunk_id,
                        "parent_chunk_id": chunk.chunk_id,
                        "parent_document_id": chunk.source_document.id,
                        "mini_chunk_index": mini_idx,
                        "content": mini_text,
                        "blurb": mini_text[:150],
                        "section_type": chunk.section_type.value,
                        "title": chunk.source_document.title,
                        "is_large_chunk": False,
                        "chunk_level": "mini",
                        "large_chunk_id": chunk.large_chunk_id,
                        "doc_summary": chunk.doc_summary,
                        "chunk_context": chunk.chunk_context,
                        "is_mini_chunk": True,
                    }
                    # 合并该 mini chunk 的自定义 payload（若提供）
                    if chunk.mini_chunk_payloads and mini_idx < len(chunk.mini_chunk_payloads):
                        mini_payload.update(chunk.mini_chunk_payloads[mini_idx])

                    points.append(
                        PointStruct(
                            id=mini_point_id,
                            vector=mini_emb,
                            payload=mini_payload,
                        )
                    )

        if points:
            total = len(points)
            batch_size = self.config.upsert_batch_size or _DEFAULT_UPSERT_BATCH_SIZE
            # 本地模式 SQLite 并发写未验证 → 串行；远程 Qdrant 支持并发 upsert
            upsert_ctx = (
                self._local_upsert_lock
                if self.config.mode == "local"
                else nullcontext()
            )
            with upsert_ctx:
                for i in range(0, total, batch_size):
                    batch = points[i : i + batch_size]
                    try:
                        self._client.upsert(
                            collection_name=self.collection_name,
                            points=batch,
                            wait=True,
                        )
                    except Exception as e:
                        raise RuntimeError(
                            f"Qdrant 批量写入失败 (batch {i//batch_size + 1}/"
                            f"{(total + batch_size - 1)//batch_size}, points {i}-{min(i+batch_size, total)-1}): {e}"
                        ) from e

    def search(
        self,
        query_embedding: Embedding,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        qdrant_filter = self._build_filter(filters)
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            SearchResult(
                id=str(point.id),
                score=point.score,
                payload=point.payload or {},
            )
            for point in response.points
        ]

    def delete_by_document_id(self, document_id: str) -> int:
        filter_ = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        )
        # 先查询有多少条匹配
        count_result = self._client.count(
            collection_name=self.collection_name,
            count_filter=filter_,
            exact=True,
        )
        count = count_result.count
        if count == 0:
            return 0

        self._client.delete(
            collection_name=self.collection_name,
            points_selector=filter_,
            wait=True,
        )
        return count

    def delete_by_chunk_id(self, document_id: str, chunk_id: int) -> bool:
        point_id = _make_point_id(document_id, chunk_id)
        # 先检查是否存在
        try:
            self._client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
            )
        except Exception:
            return False

        self._client.delete(
            collection_name=self.collection_name,
            points_selector=[point_id],
            wait=True,
        )
        return True

    def get_chunk_count(self) -> int:
        if not self.collection_exists():
            return 0
        result = self._client.count(collection_name=self.collection_name, exact=True)
        return result.count

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    def _build_filter(
        self, filters: dict[str, Any] | None
    ) -> Filter | None:
        """将简单字典转换为 Qdrant Filter。"""
        if not filters:
            return None

        conditions: list[Any] = []
        for key, value in filters.items():
            conditions.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            )

        if not conditions:
            return None
        return Filter(must=conditions)
