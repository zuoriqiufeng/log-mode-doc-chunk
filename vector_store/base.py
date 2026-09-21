"""向量数据库抽象接口（参考自 Onyx DocumentIndex 接口设计）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from models import Embedding
from models import IndexChunk


@dataclass
class SearchResult:
    """向量搜索结果"""

    id: str
    score: float
    payload: dict[str, Any]


class BaseVectorStore(ABC):
    """向量数据库抽象基类。

    所有向量存储后端（Qdrant、Milvus、Pinecone 等）必须实现此接口。
    参考自 Onyx document_index/interfaces_new.py 的 Indexable + Deletable + HybridCapable。
    """

    @property
    @abstractmethod
    def collection_name(self) -> str:
        """返回当前使用的 Collection 名称。"""
        raise NotImplementedError

    @abstractmethod
    def collection_exists(self) -> bool:
        """检查 Collection 是否存在。"""
        raise NotImplementedError

    @abstractmethod
    def create_collection(self, dimension: int) -> None:
        """创建 Collection（指定向量维度）。

        Args:
            dimension: 向量维度（如 1536 for OpenAI, 384 for all-MiniLM-L6-v2）
        """
        raise NotImplementedError

    @abstractmethod
    def upsert_chunks(self, chunks: list[IndexChunk]) -> None:
        """批量写入或更新 chunk 向量。

        Args:
            chunks: 带嵌入向量的 IndexChunk 列表
        """
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query_embedding: Embedding,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """向量相似度搜索。

        Args:
            query_embedding: 查询向量
            top_k: 返回结果数量上限
            filters: 可选的 payload 过滤条件

        Returns:
            按相似度降序排列的搜索结果列表
        """
        raise NotImplementedError

    @abstractmethod
    def delete_by_document_id(self, document_id: str) -> int:
        """删除指定文档的所有 chunk。

        Args:
            document_id: 文档 ID

        Returns:
            删除的 chunk 数量
        """
        raise NotImplementedError

    @abstractmethod
    def delete_by_chunk_id(self, document_id: str, chunk_id: int) -> bool:
        """删除指定 chunk。

        Args:
            document_id: 文档 ID
            chunk_id: chunk ID

        Returns:
            是否成功删除
        """
        raise NotImplementedError

    @abstractmethod
    def get_chunk_count(self) -> int:
        """获取 Collection 中的总 chunk 数量。"""
        raise NotImplementedError
