"""图片段落分块（参考 Onyx ImageChunker）。"""

from __future__ import annotations

from models import DocAwareChunk, Document, Section, SectionType
from utils import clean_text


def chunk_image_section(section: Section) -> DocAwareChunk | None:
    """处理图片段落：每个图片成为一个独立 chunk。"""
    if section.type != SectionType.IMAGE or not section.image_file_id:
        return None
    section_text = clean_text(str(section.text or ""))
    return DocAwareChunk(
        source_document=Document(id="", semantic_identifier="", sections=[]),
        chunk_id=0,
        content=section_text or "[Image]",
        blurb=section_text[:100] if section_text else "[Image]",
        section_type=SectionType.IMAGE,
        chunk_level="image",
        image_file_id=section.image_file_id,
    )
