#!/usr/bin/env python3
"""
PDF 处理与分块示例（支持文本、图片、表格）

本示例调用 Onyx 项目的处理思路，复用其核心代码逻辑：
- PDF 提取：pypdf（Onyx 使用的库）
- 分块：chonkie.SentenceChunker（Onyx 使用的分块库）
- 图片/表格分块：内联 Onyx 的 ImageChunker / TabularChunker 核心逻辑

参考的 Onyx 源文件：
- backend/onyx/file_processing/extract_file_text.py
- backend/onyx/connectors/models.py
- backend/onyx/indexing/chunker.py
- backend/onyx/indexing/chunking/document_chunker.py
- backend/onyx/indexing/chunking/image_section_chunker.py
- backend/onyx/indexing/chunking/tabular_section_chunker.py
- backend/onyx/indexing/chunking/section_chunker.py
- backend/onyx/indexing/chunking/text_section_chunker.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from pypdf import PdfReader
from PIL import Image
from chonkie import SentenceChunker


# =============================================================================
# 常量定义（参考自 Onyx: backend/onyx/configs/constants.py）
# =============================================================================
TEXT_SECTION_SEPARATOR = "\n\n"
RETURN_SEPARATOR = "\n"
SECTION_SEPARATOR = "\n\n"


# =============================================================================
# SectionType 与数据模型（参考自 Onyx: backend/onyx/connectors/models.py）
# =============================================================================

class SectionType(str, Enum):
    """段落类型（Onyx SectionType 的复刻）"""
    TEXT = "text"
    IMAGE = "image"
    TABULAR = "tabular"


@dataclass
class Section:
    """文档段落基类（Onyx Section 的简化版）"""
    type: SectionType
    text: str | None = None
    link: str | None = None
    image_file_id: str | None = None
    heading: str | None = None


@dataclass
class Document:
    """文档模型（Onyx Document 的简化版）"""
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
        return TEXT_SECTION_SEPARATOR.join(
            str(section.text or "") for section in self.sections
        )


@dataclass
class DocAwareChunk:
    """分块结果模型（Onyx DocAwareChunk 的简化版）"""
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


# =============================================================================
# PDF 提取（参考自 Onyx: backend/onyx/file_processing/extract_file_text.py）
# =============================================================================

def read_pdf_file(
    file: io.IOBase,
    extract_images: bool = False,
) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
    """从 PDF 提取文本、元数据和嵌入图片。

    参考：backend/onyx/file_processing/extract_file_text.py::read_pdf_file
    """
    metadata: dict[str, Any] = {}
    extracted_images: list[tuple[bytes, str]] = []

    try:
        pdf_reader = PdfReader(file)

        if pdf_reader.is_encrypted:
            try:
                if pdf_reader.decrypt("") == 0:
                    return "", metadata, []
            except Exception:
                return "", metadata, []

        # 提取 PDF 元数据
        if pdf_reader.metadata is not None:
            for key, value in pdf_reader.metadata.items():
                clean_key = key.lstrip("/")
                if isinstance(value, str) and value.strip():
                    metadata[clean_key] = value
                elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                    metadata[clean_key] = ", ".join(value)

        # 提取每页文本
        text = TEXT_SECTION_SEPARATOR.join(
            page.extract_text() or "" for page in pdf_reader.pages
        )

        # 提取嵌入图片
        if extract_images:
            for page_num, page in enumerate(pdf_reader.pages):
                for image_file_object in page.images:
                    try:
                        image = Image.open(io.BytesIO(image_file_object.data))
                        img_byte_arr = io.BytesIO()
                        image.save(img_byte_arr, format=image.format or "PNG")
                        img_bytes = img_byte_arr.getvalue()
                        image_format = image.format.lower() if image.format else "png"
                        image_name = f"page_{page_num + 1}_image_{image_file_object.name}.{image_format}"
                        extracted_images.append((img_bytes, image_name))
                    except Exception as e:
                        print(f"[WARN] Failed to extract image: {e}", file=sys.stderr)

        return text, metadata, extracted_images

    except Exception as e:
        print(f"[ERROR] PDF 提取失败: {e}", file=sys.stderr)
        return "", metadata, []


# =============================================================================
# 表格识别与解析（启发式方法，参考 Onyx 的 TabularSection 处理思路）
# =============================================================================

def detect_and_parse_table(text: str) -> tuple[str, str] | None:
    """从文本中检测并解析表格区域。

    启发式策略：
    1. 查找 "Table" / "表格" 标题附近的内容
    2. 检测连续的短行（每行 <40 字符），可能是表格单元格
    3. 尝试按固定列数重建 CSV

    返回: (table_heading, csv_text) 或 None
    """
    lines = text.splitlines()

    # 策略：查找明确的表格标题，如 "Table" / "Comparison Table" / 列头模式
    table_start = -1
    for i, line in enumerate(lines):
        # 匹配明确的表格标题，避免匹配普通文本中的 "tables" 等词
        if re.search(r"(?i)(comparison\s+table|connector\s+comparison|表格|table:)\b", line):
            table_start = i
            break

    # 备用策略：检测列头模式（如 "Connector\nType\nReal-time\nPermissions"）
    if table_start == -1:
        for i in range(len(lines) - 3):
            # 检测是否有一行看起来像列头序列
            if lines[i].strip() == "Connector" and lines[i+1].strip() == "Type":
                table_start = max(0, i - 2)
                break

    if table_start == -1:
        return None

    heading = lines[table_start] if table_start < len(lines) else ""

    # 收集连续的短行（可能是表格单元格）
    # 跳过描述性长文本，允许中间有短行分隔
    table_lines: list[str] = []
    consecutive_short = 0
    for j in range(table_start + 1, len(lines)):
        line = lines[j].strip()
        if not line:
            if consecutive_short >= 4:
                break
            continue
        # 短行（<50字符）认为是表格单元格
        if len(line) <= 50:
            table_lines.append(line)
            consecutive_short += 1
        else:
            # 长行：如果已经有足够短行则停止，否则跳过
            if consecutive_short >= 8:
                break
            # 否则跳过这行（可能是描述文本）

    if len(table_lines) < 8:
        return None

    # 尝试推断列数：通常表格有 2-5 列
    # 对于本示例，我们知道有 4 列：Connector, Type, Real-time, Permissions
    # 使用启发式：如果行数能被 4 整除，假设 4 列
    best_cols = 4
    for cols in [3, 4, 5, 2]:
        if len(table_lines) % cols == 0:
            best_cols = cols
            break

    # 重建 CSV
    csv_lines = []
    for i in range(0, len(table_lines), best_cols):
        row = table_lines[i:i + best_cols]
        if len(row) == best_cols:
            csv_lines.append(row)

    if not csv_lines:
        return None

    # 生成 CSV 字符串
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_lines)
    return heading, output.getvalue()


def parse_csv_string(csv_text: str) -> list[dict[str, str]]:
    """解析 CSV 文本为行字典列表。"""
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
            # 填充缺失值
            padded = row + [""] * (len(headers) - len(row))
            rows.append(dict(zip(headers, padded)))
    return rows


# =============================================================================
# 分块器核心逻辑（参考自 Onyx 的 section_chunker.py 及子类）
# =============================================================================

def clean_text(text: str) -> str:
    """清理文本（参考 Onyx utils.text_processing.clean_text）"""
    return text.strip()


def extract_blurb(text: str, max_chars: int = 150) -> str:
    """从文本提取简短摘要。"""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("."))
    if last_period > 20:
        return truncated[:last_period + 1]
    return truncated + "..."


# ---------------------------------------------------------------------------
# ImageChunker（参考自 Onyx: backend/onyx/indexing/chunking/image_section_chunker.py）
# ---------------------------------------------------------------------------

def chunk_image_section(section: Section) -> DocAwareChunk | None:
    """处理图片段落：每个图片生成一个独立的 chunk。

    参考：ImageChunker.chunk_section
    """
    if section.type != SectionType.IMAGE or not section.image_file_id:
        return None

    section_text = clean_text(str(section.text or ""))
    return DocAwareChunk(
        source_document=Document(id="", semantic_identifier="", sections=[]),
        chunk_id=0,
        content=section_text or "[Image]",
        blurb=section_text[:100] if section_text else "[Image]",
        section_type=SectionType.IMAGE,
        image_file_id=section.image_file_id,
    )


# ---------------------------------------------------------------------------
# TabularChunker（简化版，参考自 Onyx 的 tabular_section_chunker.py）
# ---------------------------------------------------------------------------

def format_row(header: list[str], row: dict[str, str]) -> str:
    """格式化表格行为 field=value 形式。
    参考：tabular_section_chunker.py::format_row
    """
    pairs = [(h, row.get(h, "")) for h in header if row.get(h, "").strip()]
    return ", ".join(f"{h}={v}" for h, v in pairs)


def chunk_tabular_section(section: Section, chunk_id_start: int = 0) -> list[DocAwareChunk]:
    """处理表格段落：按行分块，每行一个 chunk。

    参考：TabularChunker.chunk_section（简化版）
    """
    if section.type != SectionType.TABULAR or not section.text:
        return []

    rows = parse_csv_string(section.text)
    if not rows:
        return []

    headers = list(rows[0].keys())
    chunks: list[DocAwareChunk] = []

    # 生成列头描述
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
                section_continuation=(i > 0),
            )
        )

    return chunks


# ---------------------------------------------------------------------------
# TextChunker（使用 chonkie，参考 Onyx 的 chunker.py）
# ---------------------------------------------------------------------------

class TokenCounter:
    """基于字符数的 token 计数器。"""
    def __init__(self, chars_per_token: int = 4):
        self.chars_per_token = chars_per_token

    def encode(self, text: str) -> list[int]:
        return list(range(len(text) // self.chars_per_token))

    def decode(self, tokens: list[int]) -> str:
        return ""


def chunk_text_sections(
    sections: list[Section],
    document: Document,
    chunk_token_limit: int = 512,
    chunk_id_start: int = 0,
) -> list[DocAwareChunk]:
    """对文本段落进行分块。

    参考：Onyx Chunker.chunk + DocumentChunker.chunk
    """
    # chonkie 的 'character' tokenizer 使用字符计数
    # 512 tokens * 4 chars/token = 2048 chars
    chunk_size_chars = chunk_token_limit * 4
    chunk_splitter = SentenceChunker(
        tokenizer="character",
        chunk_size=chunk_size_chars,
        chunk_overlap=0,
        approximate=True,
    )

    # 合并所有文本段落
    full_text = TEXT_SECTION_SEPARATOR.join(
        str(s.text or "") for s in sections if s.type == SectionType.TEXT
    )

    if not full_text:
        return []

    # 使用 chonkie 分块
    chonkie_chunks = chunk_splitter.chunk(full_text)

    chunks: list[DocAwareChunk] = []
    title_prefix = (document.title or "") + RETURN_SEPARATOR if document.title else ""

    for idx, chonkie_chunk in enumerate(chonkie_chunks):
        chunk_text = chonkie_chunk.text
        chunks.append(
            DocAwareChunk(
                source_document=document,
                chunk_id=chunk_id_start + idx,
                content=chunk_text,
                blurb=extract_blurb(chunk_text, 150),
                section_type=SectionType.TEXT,
                title_prefix=title_prefix,
                section_continuation=(idx > 0),
            )
        )

    return chunks


# =============================================================================
# 主流程：PDF -> Sections -> Chunks
# =============================================================================

def process_pdf(pdf_path: str, output_dir: str = "chunk") -> tuple[Document, list[DocAwareChunk], list[tuple[bytes, str]]]:
    """处理 PDF 文件：提取文本、图片、表格，然后分块。"""

    print(f"\n{'='*70}")
    print(f"处理文件: {pdf_path}")
    print(f"{'='*70}")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 1. 读取 PDF（提取文本 + 图片）
    with open(pdf_path, "rb") as f:
        text, metadata, images = read_pdf_file(f, extract_images=True)

    print(f"\n[1] PDF 提取完成")
    print(f"    文本长度: {len(text)} 字符")
    print(f"    提取图片数: {len(images)}")
    print(f"    元数据: {json.dumps(metadata, ensure_ascii=False, indent=2)}")

    # 2. 保存提取的图片到输出目录
    image_sections: list[Section] = []
    for img_idx, (img_bytes, img_name) in enumerate(images):
        img_filename = f"image_{img_idx:03d}_{os.path.basename(img_name)}"
        img_path = os.path.join(images_dir, img_filename)
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        print(f"    图片已保存: {img_path} ({len(img_bytes)} bytes)")
        image_sections.append(
            Section(
                type=SectionType.IMAGE,
                text=f"[嵌入图片: {img_name}]",
                image_file_id=img_path,
            )
        )

    # 3. 识别表格并解析
    table_result = detect_and_parse_table(text)
    table_sections: list[Section] = []
    text_for_remaining = text

    if table_result:
        heading, csv_text = table_result
        print(f"\n[2] 检测到表格: '{heading}'")
        print(f"    CSV 行数: {len(csv_text.strip().splitlines())}")
        table_sections.append(
            Section(
                type=SectionType.TABULAR,
                text=csv_text,
                heading=heading,
            )
        )
        # 从文本中移除表格部分（简化处理）
        # 实际中需要精确定位表格区域

    # 4. 构建文本段落
    # 分割文本为自然段落，过滤掉表格区域
    # 从文本中移除表格部分，避免重复索引
    text_without_table = text
    if table_result:
        heading, csv_text = table_result
        # 尝试从文本中移除表格行
        table_lines_set = set(line.strip() for line in csv_text.strip().splitlines())
        # 也尝试匹配原始表格文本行
        remaining_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            # 如果这行是表格内容的一部分，跳过
            if stripped in table_lines_set or stripped == heading:
                continue
            remaining_lines.append(line)
        text_without_table = "\n".join(remaining_lines)

    paragraphs = [p.strip() for p in text_without_table.split(TEXT_SECTION_SEPARATOR) if p.strip()]
    text_sections = [Section(type=SectionType.TEXT, text=p) for p in paragraphs]

    # 5. 构建 Document 对象
    all_sections = text_sections + image_sections + table_sections
    document = Document(
        id=pdf_path,
        semantic_identifier=pdf_path,
        sections=all_sections,
        title=metadata.get("Title") or os.path.basename(pdf_path),
        metadata=metadata,
    )

    print(f"\n[3] 构建 Document 对象")
    print(f"    ID: {document.id}")
    print(f"    标题: {document.title}")
    print(f"    总段落数: {len(document.sections)}")
    print(f"      - 文本段落: {len(text_sections)}")
    print(f"      - 图片段落: {len(image_sections)}")
    print(f"      - 表格段落: {len(table_sections)}")

    # 6. 分块处理
    print(f"\n[4] 开始分块")
    all_chunks: list[DocAwareChunk] = []
    chunk_id = 0

    # 6.1 文本段落分块
    text_chunks = chunk_text_sections(
        text_sections, document, chunk_token_limit=512, chunk_id_start=chunk_id
    )
    for c in text_chunks:
        c.chunk_id = chunk_id
        all_chunks.append(c)
        chunk_id += 1

    # 6.2 图片段落分块（参考 ImageChunker）
    for section in image_sections:
        chunk = chunk_image_section(section)
        if chunk:
            chunk.source_document = document
            chunk.chunk_id = chunk_id
            all_chunks.append(chunk)
            chunk_id += 1

    # 6.3 表格段落分块（参考 TabularChunker）
    for section in table_sections:
        tabular_chunks = chunk_tabular_section(section, chunk_id_start=chunk_id)
        for c in tabular_chunks:
            c.source_document = document
            all_chunks.append(c)
            chunk_id += 1

    print(f"    生成总 chunk 数: {len(all_chunks)}")
    print(f"      - 文本 chunks: {len([c for c in all_chunks if c.section_type == SectionType.TEXT])}")
    print(f"      - 图片 chunks: {len([c for c in all_chunks if c.section_type == SectionType.IMAGE])}")
    print(f"      - 表格 chunks: {len([c for c in all_chunks if c.section_type == SectionType.TABULAR])}")

    return document, all_chunks, images


def print_chunks(chunks: list[DocAwareChunk]) -> None:
    """打印分块结果详情。"""

    text_chunks = [c for c in chunks if c.section_type == SectionType.TEXT]
    image_chunks = [c for c in chunks if c.section_type == SectionType.IMAGE]
    table_chunks = [c for c in chunks if c.section_type == SectionType.TABULAR]

    print(f"\n{'='*70}")
    print("分块详情")
    print(f"{'='*70}")

    if text_chunks:
        print(f"\n--- 文本 Chunks ({len(text_chunks)} 个) ---")
        for chunk in text_chunks:
            print(f"\n[Chunk {chunk.chunk_id}] (文本)")
            print(f"  Blurb: {chunk.blurb[:80]}...")
            print(f"  内容长度: {len(chunk.content)} 字符")
            print(f"  内容预览:")
            preview = chunk.content[:180].replace("\n", " ")
            print(f"    {preview}{'...' if len(chunk.content) > 180 else ''}")

    if image_chunks:
        print(f"\n--- 图片 Chunks ({len(image_chunks)} 个) ---")
        for chunk in image_chunks:
            print(f"\n[Chunk {chunk.chunk_id}] (图片)")
            print(f"  Image ID: {chunk.image_file_id}")
            print(f"  Content: {chunk.content}")

    if table_chunks:
        print(f"\n--- 表格 Chunks ({len(table_chunks)} 个) ---")
        for chunk in table_chunks:
            print(f"\n[Chunk {chunk.chunk_id}] (表格)")
            print(f"  内容:")
            for line in chunk.content.split("\n"):
                print(f"    {line}")

    print(f"\n{'='*70}")
    print("统计")
    print(f"{'='*70}")
    print(f"  文本 chunk 数: {len(text_chunks)}")
    print(f"  图片 chunk 数: {len(image_chunks)}")
    print(f"  表格 chunk 数: {len(table_chunks)}")
    print(f"  总 chunk 数: {len(chunks)}")


def save_chunks_to_directory(
    chunks: list[DocAwareChunk],
    images: list[tuple[bytes, str]],
    output_dir: str,
) -> None:
    """将分块结果保存到指定目录。

    文件结构:
      output_dir/
        chunks.json          # 所有 chunk 的元数据和内容
        chunk_000.txt        # 每个 chunk 的文本内容
        chunk_001.txt
        ...
        images/              # 提取的嵌入图片
          image_000_xxx.png
          ...
    """
    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 1. 保存所有 chunk 元数据到 JSON
    chunks_data = []
    for chunk in chunks:
        chunks_data.append({
            "chunk_id": chunk.chunk_id,
            "section_type": chunk.section_type.value,
            "content_length": len(chunk.content),
            "blurb": chunk.blurb,
            "title_prefix": chunk.title_prefix,
            "section_continuation": chunk.section_continuation,
            "is_large_chunk": chunk.is_large_chunk,
            "image_file_id": chunk.image_file_id,
            "source_document_id": chunk.source_document.id,
            "source_document_title": chunk.source_document.title,
        })

    chunks_json_path = os.path.join(output_dir, "chunks.json")
    with open(chunks_json_path, "w", encoding="utf-8") as f:
        json.dump(chunks_data, f, ensure_ascii=False, indent=2)

    # 2. 每个 chunk 保存为单独的文本文件
    for chunk in chunks:
        chunk_file = os.path.join(output_dir, f"chunk_{chunk.chunk_id:03d}.txt")
        with open(chunk_file, "w", encoding="utf-8") as f:
            f.write(f"# Chunk {chunk.chunk_id}\n")
            f.write(f"# Type: {chunk.section_type.value}\n")
            f.write(f"# Blurb: {chunk.blurb}\n")
            f.write(f"# Source: {chunk.source_document.semantic_identifier}\n")
            f.write("-" * 60 + "\n")
            f.write(chunk.content)
            f.write("\n")

    # 3. 保存提取的图片
    saved_images = []
    for img_idx, (img_bytes, img_name) in enumerate(images):
        img_filename = f"image_{img_idx:03d}_{os.path.basename(img_name)}"
        img_path = os.path.join(images_dir, img_filename)
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        saved_images.append(img_filename)

    print(f"\n[5] 结果已保存到: {output_dir}")
    print(f"    chunks.json: 包含 {len(chunks_data)} 个 chunk 的元数据")
    print(f"    chunk_xxx.txt: {len(chunks)} 个文本文件")
    print(f"    images/: {len(saved_images)} 张提取的图片")


def main() -> int:
    # 支持命令行参数: python pdf_chunk_demo.py <pdf_path> [output_dir]
    if len(sys.argv) >= 2:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "sample.pdf"

    if len(sys.argv) >= 3:
        output_dir = sys.argv[2]
    else:
        output_dir = "chunk"

    if not os.path.exists(pdf_path):
        print(f"错误: 找不到 {pdf_path}")
        return 1

    document, chunks, images = process_pdf(pdf_path, output_dir=output_dir)
    print_chunks(chunks)
    save_chunks_to_directory(chunks, images, output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
