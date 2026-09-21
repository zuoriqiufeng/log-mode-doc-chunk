"""日志模式分块器：每条模式生成 1 个 standard chunk + 2-4 个 mini chunk。"""

from __future__ import annotations

from models import DocAwareChunk, Document, Section, SectionType
from log_patterns.models import LogPattern
from log_patterns.payload import build_pattern_payload


class LogPatternChunker:
    """将 LogPattern 列表转换为 DocAwareChunk 列表。"""

    def __init__(self, document_id_prefix: str = "log_pattern"):
        self.document_id_prefix = document_id_prefix

    def chunk(
        self,
        patterns: list[LogPattern],
        chunk_id_start: int = 0,
    ) -> list[DocAwareChunk]:
        """分块入口。

        每个 pattern 产生：
        - 1 个 standard chunk（chunk_level="log_pattern_standard"）
        - 2-4 个 mini chunk（chunk_level="mini"）
        """
        chunks: list[DocAwareChunk] = []
        for idx, pattern in enumerate(patterns):
            doc_id = f"{self.document_id_prefix}_{pattern.pattern_id}"
            document = Document(
                id=doc_id,
                semantic_identifier=pattern.pattern_id,
                sections=[
                    Section(type=SectionType.TEXT, text=pattern.full_text())
                ],
                source="LOG_PATTERN",
                metadata={"pattern_id": pattern.pattern_id},
                title=pattern.pattern_id,
            )

            minis = pattern.mini_texts()
            standard_payload = build_pattern_payload(pattern, chunk_type="standard")
            mini_payloads = [
                build_pattern_payload(pattern, chunk_type="mini")
                for _ in minis
            ]
            # 给每个 mini payload 增加内容标识，便于调试
            for i, mini_text in enumerate(minis):
                mini_payloads[i]["mini_content_preview"] = mini_text[:100]

            chunk = DocAwareChunk(
                source_document=document,
                chunk_id=chunk_id_start + idx,
                content=pattern.full_text(),
                blurb=pattern.fingerprint_text[:150],
                section_type=SectionType.TEXT,
                chunk_level="log_pattern_standard",
                mini_chunk_texts=minis,
                mini_chunk_offsets=[],
                custom_payload=standard_payload,
                mini_chunk_payloads=mini_payloads,
            )
            chunks.append(chunk)

        return chunks
