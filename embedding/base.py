"""嵌入模型抽象基类 + 富化内容生成（参考自 Onyx 架构）。

对应 Onyx 中的两层:
    - generate_enriched_content_for_chunk_embedding
      → backend/onyx/document_index/chunk_content_enrichment.py
    - BaseEmbeddingModel.encode()
      → backend/onyx/natural_language_processing/search_nlp_models.py (EmbeddingModel)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from embedding.models import Embedding

if TYPE_CHECKING:
    from models import DocAwareChunk


def generate_enriched_content_for_chunk_embedding(chunk: DocAwareChunk) -> str:
    """生成用于嵌入的富化内容。

    组合顺序: title_prefix + doc_summary + content + chunk_context + metadata_suffix_semantic
    （参考自 Onyx generate_enriched_content_for_chunk_embedding）
    """
    return (
        f"{chunk.title_prefix}"
        f"{chunk.doc_summary}"
        f"{chunk.content}"
        f"{chunk.chunk_context}"
        f"{chunk.metadata_suffix_semantic}"
    )


class BaseEmbeddingModel(ABC):
    """嵌入模型抽象基类。

    所有嵌入后端（OpenAI、本地模型等）必须实现此接口。
    参考自 Onyx EmbeddingModel / CloudEmbedding 的分层设计。
    """

    @abstractmethod
    def encode(self, texts: list[str]) -> list[Embedding]:
        """将文本列表编码为向量列表。

        Args:
            texts: 待编码的文本列表

        Returns:
            与 texts 一一对应的向量列表
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称。"""
        raise NotImplementedError
