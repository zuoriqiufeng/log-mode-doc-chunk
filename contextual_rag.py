"""Contextual RAG 上下文增强（参考 Onyx indexing_pipeline.py）

为每个 chunk 生成:
- doc_summary: 文档级摘要
- chunk_context: chunk 在文档中的上下文描述

使用 LLM (OpenAI) 或基于规则的回退实现。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import DocAwareChunk, Document

# ---------------------------------------------------------------------------
# Prompt 模板（来自 Onyx backend/onyx/prompts/contextual_retrieval.py）
# ---------------------------------------------------------------------------

DOCUMENT_SUMMARY_PROMPT = """\u003cdocument\u003e
{document}
\u003c/document\u003e
Please give a short succinct summary of the entire document. Answer only with the succinct summary and nothing else.
""".rstrip()

CONTEXTUAL_RAG_PROMPT1 = """\u003cdocument\u003e
{document}
\u003c/document\u003e
Here is the chunk we want to situate within the whole document"""

CONTEXTUAL_RAG_PROMPT2 = """\u003cchunk\u003e
{chunk}
\u003c/chunk\u003e
Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else.
""".rstrip()

# ---------------------------------------------------------------------------
# LLM 调用（可选：需要 OPENAI_API_KEY）
# ---------------------------------------------------------------------------

def _has_openai() -> bool:
    try:
        import openai
        return True
    except ImportError:
        return False


def _call_llm(prompt: str, max_tokens: int = 256) -> str:
    """调用 OpenAI LLM 生成文本。未配置时返回空字符串。"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or not _has_openai():
        return ""

    import openai

    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[WARN] LLM 调用失败: {e}")
        return ""


# ---------------------------------------------------------------------------
# 基于规则的回退实现（无需 LLM）
# ---------------------------------------------------------------------------

def _rule_based_doc_summary(document: Document, max_chars: int = 300) -> str:
    """基于规则的文档摘要：取文档前 N 个字符的标题+内容概述。"""
    text = document.get_text_content()
    title = document.title or ""
    prefix = f"{title}\n" if title else ""
    content = prefix + text
    if len(content) <= max_chars:
        return content.strip()
    truncated = content[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("."))
    if last_period > 50:
        return truncated[: last_period + 1].strip()
    return (truncated + "...").strip()


def _rule_based_chunk_context(
    chunk: DocAwareChunk, all_chunks: list[DocAwareChunk], max_chars: int = 200
) -> str:
    """基于规则的 chunk 上下文：提取相邻 chunk 的关键信息作为上下文。"""
    doc_id = chunk.source_document.id
    doc_chunks = [c for c in all_chunks if c.source_document.id == doc_id and not c.is_large_chunk]

    try:
        idx = doc_chunks.index(chunk)
    except ValueError:
        return ""

    parts: list[str] = []
    if idx > 0:
        prev_blurb = doc_chunks[idx - 1].blurb[:80]
        if prev_blurb:
            parts.append(f"Previous: {prev_blurb}")
    if idx < len(doc_chunks) - 1:
        next_blurb = doc_chunks[idx + 1].blurb[:80]
        if next_blurb:
            parts.append(f"Next: {next_blurb}")

    context = "; ".join(parts)
    if len(context) > max_chars:
        return context[:max_chars] + "..."
    return context


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def add_contextual_rag(
    chunks: list[DocAwareChunk],
    use_llm: bool = False,
    max_doc_chars_for_llm: int = 4000,
    max_chunk_chars_for_llm: int = 2000,
) -> list[DocAwareChunk]:
    """
    为所有 chunk 添加 doc_summary 和 chunk_context。

    Args:
        chunks: 已完成分块的 DocAwareChunk 列表
        use_llm: 是否使用 OpenAI LLM（需配置 OPENAI_API_KEY）。
                 False 时使用基于规则的回退实现。
        max_doc_chars_for_llm: 传给 LLM 的文档最大字符数
        max_chunk_chars_for_llm: 传给 LLM 的 chunk 最大字符数
    """
    if not chunks:
        return chunks

    # 按文档分组
    from collections import defaultdict

    doc_chunks: dict[str, list[DocAwareChunk]] = defaultdict(list)
    for c in chunks:
        doc_chunks[c.source_document.id].append(c)

    for doc_id, doc_chunk_list in doc_chunks.items():
        document = doc_chunk_list[0].source_document

        # --- 1. 文档摘要 ---
        if use_llm:
            doc_text = document.get_text_content()[:max_doc_chars_for_llm]
            prompt = DOCUMENT_SUMMARY_PROMPT.format(document=doc_text)
            doc_summary = _call_llm(prompt, max_tokens=256)
        else:
            doc_summary = _rule_based_doc_summary(document)

        for c in doc_chunk_list:
            c.doc_summary = doc_summary

        # --- 2. Chunk 上下文 ---
        for c in doc_chunk_list:
            if use_llm:
                doc_text = document.get_text_content()[:max_doc_chars_for_llm]
                chunk_text = c.content[:max_chunk_chars_for_llm]
                prompt = (
                    CONTEXTUAL_RAG_PROMPT1.format(document=doc_text)
                    + "\n"
                    + CONTEXTUAL_RAG_PROMPT2.format(chunk=chunk_text)
                )
                c.chunk_context = _call_llm(prompt, max_tokens=256)
            else:
                c.chunk_context = _rule_based_chunk_context(c, chunks)

    return chunks
