"""向量数据库存储包（参考自 Onyx document_index 架构）。

支持 Qdrant 向量数据库，提供 chunk 的写入、搜索、删除等操作。

模块结构:
    base.py           — BaseVectorStore 抽象接口 + SearchResult
    qdrant_config.py  — qdrant.yml 配置管理
    qdrant_store.py   — Qdrant 实现
    factory.py        — create_vector_store 工厂
    searcher.py       — Searcher 查询器（mini-chunk 搜索 + large chunk 聚合）

使用示例:
    from vector_store import create_vector_store, Searcher

    store = create_vector_store()
    store.upsert_chunks(index_chunks)

    searcher = Searcher(store, embedding_model)
    results = searcher.search("查询文本", top_k=5)
"""

from vector_store.base import BaseVectorStore
from vector_store.base import SearchResult
from vector_store.factory import create_vector_store
from vector_store.qdrant_store import QdrantVectorStore
from vector_store.searcher import RetrievalResult
from vector_store.searcher import Searcher

__all__ = [
    "BaseVectorStore",
    "create_vector_store",
    "QdrantVectorStore",
    "SearchResult",
    "Searcher",
    "RetrievalResult",
]
