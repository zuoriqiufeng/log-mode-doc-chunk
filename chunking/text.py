"""文本段落分块：标准 chunk + mini-chunk。"""

from __future__ import annotations

from typing import Any

from models import DocAwareChunk, Document, Section, SectionType
from utils import extract_blurb


def split_mini_chunks(
    chunk_text: str,
    mini_chunk_splitter: Any,
) -> tuple[list[str], list[tuple[int, int]]] | None:
    """将 chunk 文本切分为 mini-chunks，并返回每个子块在原文中的起止偏移。

    返回 (texts, offsets)，其中 offsets[i] = (start, end) 表示第 i 个 mini chunk
    在 chunk_text 中的字节/字符位置，便于后续把 mini chunk 命中结果映射回原文。
    """
    if not mini_chunk_splitter or not chunk_text.strip():
        return None

    mini_texts = [c.text for c in mini_chunk_splitter.chunk(chunk_text)]
    if not mini_texts:
        return None

    offsets: list[tuple[int, int]] = []
    search_start = 0
    for mt in mini_texts:
        pos = chunk_text.find(mt, search_start)
        if pos == -1:
            # 容错：如果顺序查找失败，回退到全局查找
            pos = chunk_text.find(mt)
        if pos == -1:
            # 仍找不到则记录为上一个结束位置（理论上不应发生）
            pos = search_start
        end = pos + len(mt)
        offsets.append((pos, end))
        search_start = end

    return mini_texts, offsets


def get_mini_chunk_texts(
    chunk_text: str,
    mini_chunk_splitter: Any,
) -> list[str] | None:
    """将 chunk 文本进一步切分为 mini-chunks（参考 Onyx get_mini_chunk_texts）"""
    result = split_mini_chunks(chunk_text, mini_chunk_splitter)
    return result[0] if result else None


def chunk_text_sections(
    sections: list[Section],
    document: Document,
    chunk_token_limit: int = 512,
    chunk_id_start: int = 0,
    mini_chunk_size: int = 150,
) -> list[DocAwareChunk]:
    """对文本段落进行分块（使用 chonkie），同时生成 mini-chunks"""
    from chonkie import SentenceChunker

    chunk_size_chars = chunk_token_limit * 4
    mini_chunk_size_chars = mini_chunk_size * 4

    chunk_splitter = SentenceChunker(
        tokenizer="character",
        chunk_size=chunk_size_chars,
        chunk_overlap=0,
        approximate=True,
    )
    mini_chunk_splitter = SentenceChunker(
        tokenizer="character",
        chunk_size=mini_chunk_size_chars,
        chunk_overlap=0,
        approximate=True,
    )

    full_text = "\n\n".join(
        str(s.text or "") for s in sections if s.type == SectionType.TEXT
    )

    if not full_text:
        return []

    chonkie_chunks = chunk_splitter.chunk(full_text)
    chunks: list[DocAwareChunk] = []
    title_prefix = (document.title or "") + "\n" if document.title else ""

    for idx, cc in enumerate(chonkie_chunks):
        chunk_text = cc.text
        mini_result = split_mini_chunks(chunk_text, mini_chunk_splitter)
        chunks.append(
            DocAwareChunk(
                source_document=document,
                chunk_id=chunk_id_start + idx,
                content=chunk_text,
                blurb=extract_blurb(chunk_text, 150),
                section_type=SectionType.TEXT,
                chunk_level="standard",
                title_prefix=title_prefix,
                section_continuation=(idx > 0),
                mini_chunk_texts=mini_result[0] if mini_result else None,
                mini_chunk_offsets=mini_result[1] if mini_result else None,
            )
        )

    return chunks
