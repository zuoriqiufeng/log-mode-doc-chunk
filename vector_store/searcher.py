"""向量搜索器：支持 mini-chunk 搜索，返回 large chunk 拼接内容。

参考 Onyx 检索逻辑设计：
- 用小块（标准 chunk / mini-chunk）向量做 ANN 搜索
- 匹配到的小块若属于某个 large chunk，则返回对应 large chunk 的完整拼接内容
- 若未归属 large chunk，则返回小块自身内容
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from embedding.base import BaseEmbeddingModel
from models import Embedding
from vector_store.base import BaseVectorStore
from vector_store.base import SearchResult


@dataclass
class RetrievalResult:
    """检索结果（参考 Onyx InferenceChunk）"""

    document_id: str
    chunk_id: int
    content: str
    score: float
    title: str
    section_type: str
    is_large_chunk: bool
    chunk_level: str
    source_chunk_ids: list[int]
    doc_summary: str
    chunk_context: str


class Searcher:
    """向量搜索器。

    职责：
    1. 将查询文本编码为向量
    2. 在向量数据库中搜索（标准 chunk + mini-chunk）
    3. 按 large chunk 聚合结果，返回拼接内容
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embedding_model: BaseEmbeddingModel,
    ) -> None:
        self.vector_store = vector_store
        self.embedding_model = embedding_model

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """搜索向量数据库，返回 large chunk 聚合后的结果。

        Args:
            query: 查询文本
            top_k: 返回结果数量上限
            filters: 可选过滤条件

        Returns:
            RetrievalResult 列表，已按 large chunk 聚合去重
        """
        # 1. 编码查询文本
        query_embeddings = self.embedding_model.encode([query])
        if not query_embeddings:
            return []
        query_embedding = query_embeddings[0]

        # 2. 向量搜索（同时匹配标准 chunk 和 mini-chunk）
        raw_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k * 3,  # 多取一些用于聚合去重
            filters=filters,
        )
        if not raw_results:
            return []

        # 3. 按 large chunk 聚合
        return self._aggregate_by_large_chunk(raw_results, top_k)

    def _aggregate_by_large_chunk(
        self,
        raw_results: list[SearchResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """将原始搜索结果按 large chunk 聚合。

        策略：
        - 若匹配到 large chunk：直接返回其内容
        - 若匹配到标准 chunk / mini-chunk 且归属 large chunk：返回对应 large chunk 内容
        - 若匹配到标准 chunk / mini-chunk 无 large chunk：返回自身内容
        - 同一 large chunk 只保留一次（取最高分数）
        """
        # large_chunk_key -> (best_score, RetrievalResult)
        large_chunk_map: dict[str, tuple[float, RetrievalResult]] = {}

        # 独立 chunk（无 large chunk 归属）结果
        standalone_results: list[tuple[float, RetrievalResult]] = []

        for result in raw_results:
            payload = result.payload
            document_id = payload.get("document_id", "")
            chunk_id = payload.get("chunk_id", -1)
            score = result.score

            # 检查是否是 large chunk 本身
            if payload.get("is_large_chunk"):
                key = f"{document_id}_large_{chunk_id}"
                if key not in large_chunk_map or score > large_chunk_map[key][0]:
                    large_chunk_map[key] = (
                        score,
                        RetrievalResult(
                            document_id=document_id,
                            chunk_id=chunk_id,
                            content=payload.get("content", ""),
                            score=score,
                            title=payload.get("title", ""),
                            section_type=payload.get("section_type", "text"),
                            is_large_chunk=True,
                            chunk_level=payload.get("chunk_level", "large"),
                            source_chunk_ids=payload.get("large_chunk_reference_ids", []),
                            doc_summary=payload.get("doc_summary", ""),
                            chunk_context=payload.get("chunk_context", ""),
                        ),
                    )
                continue

            # 检查是否归属 large chunk
            large_chunk_id = payload.get("large_chunk_id")
            if large_chunk_id is not None:
                # 归属 large chunk，需要获取 large chunk 内容
                key = f"{document_id}_large_{large_chunk_id}"
                if key not in large_chunk_map or score > large_chunk_map[key][0]:
                    large_chunk_content = self._get_large_chunk_content(
                        document_id, large_chunk_id
                    )
                    large_chunk_map[key] = (
                        score,
                        RetrievalResult(
                            document_id=document_id,
                            chunk_id=large_chunk_id,
                            content=large_chunk_content or payload.get("content", ""),
                            score=score,
                            title=payload.get("title", ""),
                            section_type="text",
                            is_large_chunk=True,
                            chunk_level=payload.get("chunk_level", "large"),
                            source_chunk_ids=[],  # 从 large chunk point 获取更准确
                            doc_summary=payload.get("doc_summary", ""),
                            chunk_context=payload.get("chunk_context", ""),
                        ),
                    )
                continue

            # 无 large chunk 归属，作为独立结果
            standalone_results.append(
                (
                    score,
                    RetrievalResult(
                        document_id=document_id,
                        chunk_id=chunk_id,
                        content=payload.get("content", ""),
                        score=score,
                        title=payload.get("title", ""),
                        section_type=payload.get("section_type", "text"),
                        is_large_chunk=False,
                        chunk_level=payload.get("chunk_level", "standard"),
                        source_chunk_ids=[chunk_id],
                        doc_summary=payload.get("doc_summary", ""),
                        chunk_context=payload.get("chunk_context", ""),
                    ),
                )
            )

        # 合并结果并按分数排序
        all_results = list(large_chunk_map.values()) + standalone_results
        all_results.sort(key=lambda x: x[0], reverse=True)

        return [r for _, r in all_results[:top_k]]

    # ------------------------------------------------------------------ #
    # 混合检索：BGE 语义 + 关键词兜底
    # ------------------------------------------------------------------ #

    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        semantic_threshold: float = 0.30,
    ) -> list[RetrievalResult]:
        """混合检索：BGE 语义搜索 + payload 关键词兜底。

        当 BGE 分数低于 threshold 时，降级为关键词精确匹配。

        Args:
            query: 搜索词（如 "-4002"）
            top_k: 返回数量
            semantic_threshold: BGE 分数低于此值触发兜底
        """
        # 1. BGE 语义搜索
        semantic_results = self.search(query, top_k=top_k * 3)

        # 2. 分离高分结果
        high_score = [r for r in semantic_results if r.score >= semantic_threshold]
        seen_ids = {f"{r.document_id}:{r.chunk_id}" for r in high_score}

        # 3. Payload keywords 精确匹配兜底
        keyword_results = self._search_by_keywords(query, top_k)

        # 4. 合并去重
        merged: dict[str, RetrievalResult] = {
            f"{r.document_id}:{r.chunk_id}": r for r in high_score
        }
        for r in keyword_results:
            uid = f"{r.document_id}:{r.chunk_id}"
            if uid not in merged:
                merged[uid] = r

        results = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _search_by_keywords(self, query: str, top_k: int) -> list[RetrievalResult]:
        """Payload keywords 字段精确匹配搜索。

        策略：
        1. 尝试 Qdrant v1.10+ 全文索引 (content 字段 text schema)
        2. Fallback: scroll + Python 端子串/关键词匹配
        """
        results: list[RetrievalResult] = []
        tokens = [t.strip() for t in query.split() if len(t.strip()) > 1]
        if not tokens:
            return results

        try:
            # Qdrant v1.10+ 全文索引搜索
            response = self.vector_store._client.query_points(
                collection_name=self.vector_store.collection_name,
                query=tokens[0],
                limit=top_k,
                with_payload=True,
            )
            for point in response.points:
                payload = point.payload or {}
                results.append(self._point_to_result(payload, point.score / 100.0 or 0.50))
        except Exception:
            # Fallback: Python 端子串/关键词匹配
            all_points, _ = self.vector_store._client.scroll(
                collection_name=self.vector_store.collection_name,
                limit=top_k * 10,
                with_payload=True,
            )
            for point in all_points:
                payload = point.payload or {}
                content = payload.get("content", "")
                keywords: list[str] = payload.get("keywords", [])
                match_content = any(t.lower() in content.lower() for t in tokens)
                match_keywords = any(
                    any(t.lower() in kw.lower() for t in tokens)
                    for kw in keywords
                )
                if match_content or match_keywords:
                    results.append(self._point_to_result(payload, 0.45))

        return results

    def _point_to_result(self, payload: dict, score: float) -> RetrievalResult:
        """将 Qdrant payload 转换为 RetrievalResult。"""
        return RetrievalResult(
            document_id=payload.get("document_id", ""),
            chunk_id=payload.get("chunk_id", -1),
            content=payload.get("content", ""),
            score=score,
            title=payload.get("title", ""),
            section_type=payload.get("section_type", "text"),
            is_large_chunk=payload.get("is_large_chunk", False),
            chunk_level=payload.get("chunk_level", "standard"),
            source_chunk_ids=[payload.get("chunk_id", -1)],
            doc_summary=payload.get("doc_summary", ""),
            chunk_context=payload.get("chunk_context", ""),
        )

    def _get_large_chunk_content(self, document_id: str, large_chunk_id: int) -> str | None:
        """从向量数据库检索 large chunk 的完整内容。"""
        try:
            from vector_store.qdrant_store import _make_point_id

            point_id = _make_point_id(document_id, large_chunk_id)
            # 需要直接访问底层 client 来 retrieve
            if hasattr(self.vector_store, "_client"):
                retrieved = self.vector_store._client.retrieve(
                    collection_name=self.vector_store.collection_name,
                    ids=[point_id],
                    with_payload=True,
                )
                if retrieved and retrieved[0].payload:
                    return retrieved[0].payload.get("content")
        except Exception:
            pass
        return None
