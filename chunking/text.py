"""文本段落分块：标准 chunk + mini-chunk。

含片长硬上限兜底（hard_split）：chonkie 的 SentenceChunker 只在句子边界合并、
无"单句超长硬切"分支，整块无分隔符时会退化为单片独大（精确项落到向量/交付
窗口之外）。hard_split 对其产物做兜底：仅超限片触发，正常片零变化。
"""

from __future__ import annotations

import re
from typing import Any

from models import DocAwareChunk, Document, Section, SectionType
from utils import extract_blurb

# 片长硬上限兜底优先采纳的分隔符：错误码清单 / 中文表格 / 英文词的天然边界
HARD_SPLIT_SEPS = (", ", "，", "；", "; ", " | ", "、", "。", " ")

# 与 bkn TOKEN_PAT 同源的 token 字符集：切点两侧均为 token 字符 = 切在 token 内部
_TOKEN_CHAR_RE = re.compile(r"[A-Za-z0-9_\-]")


def hard_split(
    text: str,
    max_chars: int,
    seps: tuple[str, ...] = HARD_SPLIT_SEPS,
    token_backoff: int = 32,
) -> tuple[list[str], list[tuple[int, int]]]:
    """片长硬上限兜底：把超限文本切成每片 <= max_chars。

    规则：在 (0, max_chars] 内找最靠右的分隔符切（切点须 >1，避免单字符片死循环）；
    找不到分隔符时在 max_chars 处硬切，但切点若落在 [A-Za-z0-9_-] 连续串内部，
    向左回退到串边界（最多 token_backoff 字符；退无可退——如单个 token 长于上限
    ——才在 max_chars 直切），避免把 -4018 这类精确项拦腰切成 -40 + 18。

    所有片都是 text 的连续切片：text[start:end] == texts[i] 且 offsets[i] == (start, end)
    （split_mini_chunks 的 find() 定位依赖此不变量）。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正整数")
    if not text:
        return [], []

    texts: list[str] = []
    offsets: list[tuple[int, int]] = []
    start = 0
    total = len(text)

    while total - start > max_chars:
        window = text[start : start + max_chars]
        cut = -1
        for sep in seps:
            pos = window.rfind(sep)
            if pos != -1 and pos + len(sep) > 1:
                cut = max(cut, pos + len(sep))
        if cut <= 0:
            cut = _token_safe_cut(text, start + max_chars, start + 1, token_backoff) - start
        texts.append(text[start : start + cut])
        offsets.append((start, start + cut))
        start += cut

    texts.append(text[start:])
    offsets.append((start, total))
    return texts, offsets


def _token_safe_cut(text: str, cut: int, floor: int, max_backoff: int) -> int:
    """把切点向左回退到 token 边界（两侧不全为 token 字符）；最多退 max_backoff 字符。"""
    limit = max(floor, cut - max_backoff)
    j = cut
    while j > limit:
        if not (_TOKEN_CHAR_RE.match(text[j - 1]) and _TOKEN_CHAR_RE.match(text[j])):
            return j
        j -= 1
    return cut


def split_mini_chunks(
    chunk_text: str,
    mini_chunk_splitter: Any,
    mini_max_chars: int | None = None,
) -> tuple[list[str], list[tuple[int, int]]] | None:
    """将 chunk 文本切分为 mini-chunks，并返回每个子块在原文中的起止偏移。

    返回 (texts, offsets)，其中 offsets[i] = (start, end) 表示第 i 个 mini chunk
    在 chunk_text 中的字节/字符位置，便于后续把 mini chunk 命中结果映射回原文。

    mini_max_chars 给定时对超过上限的退化片做 hard_split 兜底（仅超限片触发，
    正常片零变化）；None 表示不设上限（保持旧行为）。
    """
    if not mini_chunk_splitter or not chunk_text.strip():
        return None

    mini_texts = [c.text for c in mini_chunk_splitter.chunk(chunk_text)]
    if not mini_texts:
        return None

    if mini_max_chars:
        fixed: list[str] = []
        for mt in mini_texts:
            if len(mt) > mini_max_chars:
                fixed.extend(hard_split(mt, mini_max_chars)[0])
            else:
                fixed.append(mt)
        mini_texts = fixed

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

    # 标准片硬上限兜底：chonkie 无"单句超长硬切"，退化片（如无分隔符的长清单）
    # 会原样超限；仅超限片触发，正常片零变化
    piece_texts: list[str] = []
    for cc in chonkie_chunks:
        if len(cc.text) > chunk_size_chars:
            piece_texts.extend(hard_split(cc.text, chunk_size_chars)[0])
        else:
            piece_texts.append(cc.text)

    chunks: list[DocAwareChunk] = []
    title_prefix = (document.title or "") + "\n" if document.title else ""

    for idx, chunk_text in enumerate(piece_texts):
        mini_result = split_mini_chunks(
            chunk_text, mini_chunk_splitter, mini_max_chars=mini_chunk_size_chars
        )
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
