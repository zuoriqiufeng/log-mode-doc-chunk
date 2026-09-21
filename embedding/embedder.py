"""Chunk 嵌入编排器（参考自 Onyx DefaultIndexingEmbedder）。

对应 Onyx:
    - backend/onyx/indexing/embedder.py
      中 DefaultIndexingEmbedder.embed_chunks() 方法

职责:
    - 构建富化文本列表（chunk content + mini-chunk texts）
    - 调用 BaseEmbeddingModel.encode() 批量编码
    - 缓存文档 title 嵌入向量
    - 将编码结果映射回 IndexChunk

不包含任何具体模型调用逻辑，全部委托给 BaseEmbeddingModel 实现。
"""

from __future__ import annotations

from dataclasses import fields

from embedding.base import BaseEmbeddingModel
from embedding.base import generate_enriched_content_for_chunk_embedding
from embedding.models import Embedding
from models import ChunkEmbedding
from models import DocAwareChunk
from models import IndexChunk


class Embedder:
    """Chunk 嵌入编排器。

    通过 BaseEmbeddingModel 接口委托具体模型实现，
    自身只负责 chunk 级别的编排逻辑。
    """

    def __init__(self, embedding_model: BaseEmbeddingModel):
        self.embedding_model = embedding_model

    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
    ) -> list[IndexChunk]:
        """为所有 chunk 生成嵌入向量。

        流程（参考自 Onyx DefaultIndexingEmbedder.embed_chunks）：
        1. 构建扁平文本列表: [chunk1_enriched, chunk1_mini1, chunk1_mini2, chunk2_enriched, ...]
        2. 批量编码所有文本（通过 embedding_model.encode）
        3. 缓存文档 title 的嵌入向量
        4. 将编码结果映射回各个 chunk
        """
        if not chunks:
            return []

        # 1. 构建扁平文本列表
        flat_chunk_texts: list[str] = []
        for chunk in chunks:
            chunk_text = (
                generate_enriched_content_for_chunk_embedding(chunk)
                or chunk.source_document.get_title_for_document_index()
                or ""
            )
            if not chunk_text:
                chunk_text = chunk.blurb or ""

            flat_chunk_texts.append(chunk_text)

            if chunk.mini_chunk_texts:
                if chunk.large_chunk_reference_ids:
                    raise RuntimeError(
                        "Large chunk 不应包含 mini-chunks"
                    )
                flat_chunk_texts.extend(chunk.mini_chunk_texts)

        # 2. 批量编码
        print(
            f"    模型后端: {self.embedding_model.__class__.__name__}"
            f" ({self.embedding_model.model_name})"
        )
        print(f"    待编码文本数: {len(flat_chunk_texts)}")
        all_embeddings = self.embedding_model.encode(flat_chunk_texts)
        print(f"    编码完成: {len(all_embeddings)} 个向量")

        # 3. 缓存文档 title 嵌入
        chunk_titles = {
            chunk.source_document.get_title_for_document_index()
            for chunk in chunks
        }
        chunk_titles_list = [t for t in chunk_titles if t]

        title_embed_dict: dict[str, Embedding] = {}
        if chunk_titles_list:
            print(f"    编码文档标题: {len(chunk_titles_list)} 个")
            title_embeddings = self.embedding_model.encode(chunk_titles_list)
            title_embed_dict = {
                title: vec for title, vec in zip(chunk_titles_list, title_embeddings)
            }

        # 4. 映射回 chunks
        embedded_chunks: list[IndexChunk] = []
        embedding_ind_start = 0

        for chunk in chunks:
            num_embeddings = 1 + (
                len(chunk.mini_chunk_texts) if chunk.mini_chunk_texts else 0
            )
            chunk_embeddings = all_embeddings[
                embedding_ind_start : embedding_ind_start + num_embeddings
            ]

            title = chunk.source_document.get_title_for_document_index()
            title_embedding = title_embed_dict.get(title) if title else None

            chunk_fields = {
                f.name: getattr(chunk, f.name) for f in fields(DocAwareChunk)
            }
            index_chunk = IndexChunk(
                **chunk_fields,
                embeddings=ChunkEmbedding(
                    full_embedding=chunk_embeddings[0],
                    mini_chunk_embeddings=chunk_embeddings[1:],
                ),
                title_embedding=title_embedding,
            )
            embedded_chunks.append(index_chunk)
            embedding_ind_start += num_embeddings

        return embedded_chunks
