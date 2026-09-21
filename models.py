"""数据模型（参考自 Onyx: backend/onyx/connectors/models.py, backend/onyx/indexing/models.py）"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Embedding 类型别名：一维浮点向量
Embedding = list[float]


class SectionType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TABULAR = "tabular"


@dataclass
class Section:
    type: SectionType
    text: str | None = None
    link: str | None = None
    image_file_id: str | None = None
    heading: str | None = None


@dataclass
class Document:
    id: str
    semantic_identifier: str
    sections: list[Section]
    source: str = "FILE"
    metadata: dict[str, Any] = field(default_factory=dict)
    doc_updated_at: str | None = None
    title: str | None = None

    def get_title_for_document_index(self) -> str | None:
        return self.title

    def get_text_content(self) -> str:
        return "\n\n".join(
            str(section.text or "") for section in self.sections
        )


@dataclass
class DocAwareChunk:
    source_document: Document
    chunk_id: int
    content: str
    blurb: str
    section_type: SectionType = SectionType.TEXT
    image_file_id: str | None = None
    source_links: dict[int, str] | None = None
    section_continuation: bool = False
    title_prefix: str = ""
    metadata_suffix_semantic: str = ""
    metadata_suffix_keyword: str = ""
    is_large_chunk: bool = False
    chunk_level: str = "standard"  # large | standard | mini | image | tabular
    mini_chunk_texts: list[str] | None = None
    mini_chunk_offsets: list[tuple[int, int]] | None = None
    large_chunk_id: int | None = None
    large_chunk_reference_ids: list[int] = field(default_factory=list)
    doc_summary: str = ""
    chunk_context: str = ""
    contextual_rag_reserved_tokens: int = 0

    # 扩展字段：供日志模式库等结构化数据携带专有 payload
    custom_payload: dict[str, Any] = field(default_factory=dict)
    mini_chunk_payloads: list[dict[str, Any]] | None = None


@dataclass
class ChunkEmbedding:
    """Chunk 的嵌入向量集合（参考自 Onyx ChunkEmbedding）"""

    full_embedding: Embedding
    mini_chunk_embeddings: list[Embedding] = field(default_factory=list)


@dataclass
class IndexChunk(DocAwareChunk):
    """带嵌入向量的 Chunk（参考自 Onyx IndexChunk）"""

    embeddings: ChunkEmbedding = field(default_factory=lambda: ChunkEmbedding([]))
    title_embedding: Embedding | None = None
