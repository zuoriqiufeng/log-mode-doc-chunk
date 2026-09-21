"""向量嵌入包（参考自 Onyx embedding 架构）。

模块结构:
    models.py         — 数据模型 (Embedding, EmbedRequest, EmbedResponse)
    base.py           — 抽象基类 BaseEmbeddingModel + 富化内容生成
    config.py         — 配置管理 (.env / 环境变量)
    openai_provider.py — OpenAI API 实现
    local_provider.py — 本地 sentence-transformers 实现
    factory.py        — create_embedding_model 工厂
    embedder.py       — Embedder 编排器 (chunk → IndexChunk)

使用示例:
    from embedding import create_embedding_model, Embedder

    model = create_embedding_model("openai", model_name="text-embedding-3-small")
    embedder = Embedder(embedding_model=model)
    index_chunks = embedder.embed_chunks(doc_aware_chunks)
"""

from embedding.base import BaseEmbeddingModel
from embedding.base import generate_enriched_content_for_chunk_embedding
from embedding.embedder import Embedder
from embedding.factory import create_embedding_model
from embedding.local_provider import LocalEmbeddingModel
from embedding.openai_provider import OpenAIEmbeddingModel

__all__ = [
    "BaseEmbeddingModel",
    "create_embedding_model",
    "Embedder",
    "generate_enriched_content_for_chunk_embedding",
    "LocalEmbeddingModel",
    "OpenAIEmbeddingModel",
]
