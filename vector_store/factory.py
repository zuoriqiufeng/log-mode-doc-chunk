"""向量存储工厂函数。"""

from __future__ import annotations

from vector_store.base import BaseVectorStore
from vector_store.qdrant_store import QdrantVectorStore


def create_vector_store(
    backend: str = "qdrant",
    **kwargs: object,
) -> BaseVectorStore:
    """创建向量存储实例。

    Args:
        backend: 向量存储后端，目前仅支持 "qdrant"。
        **kwargs: 传递给具体实现的额外参数。

    Returns:
        BaseVectorStore 实例。
    """
    if backend == "qdrant":
        return QdrantVectorStore(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"不支持的向量存储后端: {backend}")
