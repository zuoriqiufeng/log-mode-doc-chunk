"""大 chunk 生成：将多个标准 chunk 合并为上下文更丰富的大 chunk。"""

from __future__ import annotations

from models import DocAwareChunk


def _combine_chunks(chunks: list[DocAwareChunk], large_chunk_id: int) -> DocAwareChunk:
    """将多个标准 chunk 合并为一个大 chunk（参考 Onyx _combine_chunks）"""
    merged = DocAwareChunk(
        source_document=chunks[0].source_document,
        chunk_id=chunks[0].chunk_id,
        blurb=chunks[0].blurb,
        content=chunks[0].content,
        source_links=chunks[0].source_links or {0: ""},
        image_file_id=None,
        section_continuation=(chunks[0].chunk_id > 0),
        title_prefix=chunks[0].title_prefix,
        metadata_suffix_semantic=chunks[0].metadata_suffix_semantic,
        metadata_suffix_keyword=chunks[0].metadata_suffix_keyword,
        is_large_chunk=True,
        chunk_level="large",
        mini_chunk_texts=None,
        large_chunk_id=large_chunk_id,
        large_chunk_reference_ids=[c.chunk_id for c in chunks],
    )
    for i in range(1, len(chunks)):
        merged.content += "\n\n" + chunks[i].content
    return merged


def generate_large_chunks(
    chunks: list[DocAwareChunk], ratio: int = 4, chunk_id_start: int = 0
) -> list[DocAwareChunk]:
    """生成大 chunk：每 ratio 个标准 chunk 合并为一个（参考 Onyx generate_large_chunks）。

    同时会为被合并的标准 chunk 设置 large_chunk_id，指向对应 large chunk 的 chunk_id。

    Args:
        chunks: 所有 chunk 列表
        ratio: 每几个标准 chunk 合并为一个 large chunk
        chunk_id_start: large chunk 的起始 chunk_id

    Returns:
        large chunk 列表
    """
    large_chunks: list[DocAwareChunk] = []
    large_chunk_id = chunk_id_start

    # 合并对象是所有非 large chunk（文本、图片、表格块都在内），不是只有文本+表格
    eligible = [c for c in chunks if not c.is_large_chunk]

    for i in range(0, len(eligible), ratio):
        group = eligible[i : i + ratio]
        if len(group) > 1:
            lc = _combine_chunks(group, large_chunk_id)
            # 为组内每个标准 chunk 设置 large_chunk_id
            for c in group:
                c.large_chunk_id = large_chunk_id
            large_chunks.append(lc)
            large_chunk_id += 1

    return large_chunks
