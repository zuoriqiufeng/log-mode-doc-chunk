"""表格段落分块（参考 Onyx TabularChunker）。"""

from __future__ import annotations

import csv
import io

from models import DocAwareChunk, Document, Section, SectionType


def parse_csv_string(csv_text: str) -> list[dict[str, str]]:
    rows = []
    reader = csv.reader(io.StringIO(csv_text))
    headers = None
    for row in reader:
        if not headers:
            headers = row
            continue
        if len(row) == len(headers):
            rows.append(dict(zip(headers, row)))
        else:
            padded = row + [""] * (len(headers) - len(row))
            rows.append(dict(zip(headers, padded)))
    return rows


def format_row(header: list[str], row: dict[str, str]) -> str:
    """参考 TabularChunker::format_row"""
    pairs = [(h, row.get(h, "")) for h in header if row.get(h, "").strip()]
    return ", ".join(f"{h}={v}" for h, v in pairs)


def chunk_tabular_section(section: Section, chunk_id_start: int = 0) -> list[DocAwareChunk]:
    """处理表格段落：每行成为一个 chunk。"""
    if section.type != SectionType.TABULAR or not section.text:
        return []

    rows = parse_csv_string(section.text)
    if not rows:
        return []

    headers = list(rows[0].keys())
    chunks: list[DocAwareChunk] = []
    column_header = "Columns: " + ", ".join(headers)

    for i, row in enumerate(rows):
        formatted = format_row(headers, row)
        content = f"{column_header}\n{formatted}"
        if section.heading:
            content = f"{section.heading}\n{content}"

        chunks.append(
            DocAwareChunk(
                source_document=Document(id="", semantic_identifier="", sections=[]),
                chunk_id=chunk_id_start + i,
                content=content,
                blurb=formatted[:100],
                section_type=SectionType.TABULAR,
                chunk_level="tabular",
                section_continuation=(i > 0),
            )
        )

    return chunks
