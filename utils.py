"""工具函数：文本清理、表格检测、结果保存与输出。"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile

from models import DocAwareChunk, SectionType


# ZIP 解压安全限制
MAX_ZIP_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_ZIP_FILES = 1000
MAX_ZIP_FILE_SIZE = 50 * 1024 * 1024  # 单个文件 50 MB


def safe_extract_zip(zip_path: str, extract_dir: str) -> tuple[list[str], list[str]]:
    """安全解压 ZIP 文件。

    返回 (extracted_paths, errors)。
    会过滤掉非法路径（如 ../etc/passwd）和 oversized 文件。
    """
    os.makedirs(extract_dir, exist_ok=True)
    extracted: list[str] = []
    errors: list[str] = []

    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_FILES:
            errors.append(f"ZIP 内文件数超过限制 {MAX_ZIP_FILES}")
            return extracted, errors

        for info in infos:
            if info.is_dir():
                continue

            # 防止 Zip Slip
            target = os.path.join(extract_dir, info.filename)
            real_extract_dir = os.path.realpath(extract_dir)
            real_target = os.path.realpath(target)
            if not real_target.startswith(real_extract_dir + os.sep):
                errors.append(f"非法路径: {info.filename}")
                continue

            # 限制单文件大小
            if info.file_size > MAX_ZIP_FILE_SIZE:
                errors.append(f"文件过大跳过: {info.filename}")
                continue

            total_size += info.file_size
            if total_size > MAX_ZIP_SIZE:
                errors.append("ZIP 总大小超过限制 100MB")
                return extracted, errors

            zf.extract(info, extract_dir)
            extracted.append(real_target)

    return extracted, errors


def find_main_markdown(extract_dir: str) -> str | None:
    """从解压目录中查找主 Markdown 文件。

    优先找 index.md / README.md，否则返回第一个 .md 文件。
    """
    md_files: list[str] = []
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(".md"):
                md_files.append(os.path.join(root, f))

    if not md_files:
        return None

    # 优先入口文件
    for name in ("index.md", "README.md", "readme.md"):
        for path in md_files:
            if os.path.basename(path).lower() == name:
                return path

    return md_files[0]


def clean_text(text: str) -> str:
    return text.strip()


def extract_blurb(text: str, max_chars: int = 150) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("."))
    if last_period > 20:
        return truncated[: last_period + 1]
    return truncated + "..."


def detect_and_parse_table(text: str) -> tuple[str, str, list[str]] | None:
    """从文本中启发式检测表格区域并解析为 CSV。

    返回 (heading, csv_text, consumed_lines)。consumed_lines 是实际写入
    CSV 的单元格原文（已 strip、保持重复；未凑成完整行的尾部零头不在其中，
    避免调用方把正文里唯一一份副本删掉）。调用方可用它把表格内容从正文
    中精确移除，避免同一内容同时进入文本块与表格块。

    已知取舍：正文散文行恰好等于某单元格文本时会被误删——分块前的文本
    多为合并后的长段落，实际碰撞概率极低。
    """
    lines = text.splitlines()

    table_start = -1
    for i, line in enumerate(lines):
        if re.search(r"(?i)(comparison\s+table|table:|表格)", line):
            table_start = i
            break

    if table_start == -1:
        for i in range(len(lines) - 3):
            if lines[i].strip() in ["Connector", "Name", "ID"]:
                table_start = max(0, i - 1)
                break

    if table_start == -1:
        return None

    heading = lines[table_start] if table_start < len(lines) else ""

    table_lines: list[str] = []
    consecutive_short = 0
    for j in range(table_start + 1, len(lines)):
        line = lines[j].strip()
        if not line:
            if consecutive_short >= 4:
                break
            continue
        if len(line) <= 50:
            table_lines.append(line)
            consecutive_short += 1
        else:
            if consecutive_short >= 8:
                break

    if len(table_lines) < 8:
        return None

    best_cols = 4
    for cols in [3, 4, 5, 2]:
        if len(table_lines) % cols == 0:
            best_cols = cols
            break

    csv_lines = []
    for i in range(0, len(table_lines), best_cols):
        row = table_lines[i : i + best_cols]
        if len(row) == best_cols:
            csv_lines.append(row)

    if not csv_lines:
        return None

    consumed_lines = [cell for row in csv_lines for cell in row]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_lines)
    return heading, output.getvalue(), consumed_lines


def save_results(
    chunks: list[DocAwareChunk],
    images: list[tuple[bytes, str]],
    output_dir: str,
) -> None:
    """保存分块结果到目录（含 mini-chunk、large chunk 和 embedding 信息）"""
    import numpy as np

    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    chunks_data = []
    embeddings_data = []
    for chunk in chunks:
        chunk_dict = {
            "chunk_id": chunk.chunk_id,
            "section_type": chunk.section_type.value,
            "content_length": len(chunk.content),
            "blurb": chunk.blurb,
            "title_prefix": chunk.title_prefix,
            "section_continuation": chunk.section_continuation,
            "is_large_chunk": chunk.is_large_chunk,
            "chunk_level": chunk.chunk_level,
            "large_chunk_id": chunk.large_chunk_id,
            "large_chunk_reference_ids": chunk.large_chunk_reference_ids,
            "mini_chunk_count": len(chunk.mini_chunk_texts) if chunk.mini_chunk_texts else 0,
            "mini_chunk_texts": chunk.mini_chunk_texts,
            "mini_chunk_offsets": chunk.mini_chunk_offsets,
            "doc_summary": chunk.doc_summary,
            "chunk_context": chunk.chunk_context,
            "image_file_id": chunk.image_file_id,
            "source_document_id": chunk.source_document.id,
            "source_document_title": chunk.source_document.title,
        }

        # 如果 chunk 包含嵌入向量，也保存到 JSON（只保存维度信息，向量存 .npy）
        if hasattr(chunk, "embeddings") and chunk.embeddings is not None:
            emb = chunk.embeddings
            has_full = bool(emb.full_embedding)
            mini_count = len(emb.mini_chunk_embeddings) if emb.mini_chunk_embeddings else 0
            chunk_dict["embedding_dim"] = len(emb.full_embedding) if has_full else 0
            chunk_dict["has_full_embedding"] = has_full
            chunk_dict["mini_embedding_count"] = mini_count

            if has_full:
                embeddings_data.append({
                    "chunk_id": chunk.chunk_id,
                    "full": emb.full_embedding,
                    "mini": emb.mini_chunk_embeddings,
                    "title": chunk.title_embedding if hasattr(chunk, "title_embedding") else None,
                })

        chunks_data.append(chunk_dict)

    with open(os.path.join(output_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunks_data, f, ensure_ascii=False, indent=2)

    # 保存 embedding 向量为 .npy 文件（便于 numpy 加载）
    if embeddings_data:
        embeddings_dir = os.path.join(output_dir, "embeddings")
        os.makedirs(embeddings_dir, exist_ok=True)
        for ed in embeddings_data:
            cid = ed["chunk_id"]
            np.save(os.path.join(embeddings_dir, f"chunk_{cid:03d}_full.npy"), np.array(ed["full"], dtype=np.float32))
            if ed["title"]:
                np.save(os.path.join(embeddings_dir, f"chunk_{cid:03d}_title.npy"), np.array(ed["title"], dtype=np.float32))
            for mi, mini_vec in enumerate(ed["mini"]):
                np.save(os.path.join(embeddings_dir, f"chunk_{cid:03d}_mini_{mi}.npy"), np.array(mini_vec, dtype=np.float32))

    for chunk in chunks:
        path = os.path.join(output_dir, f"chunk_{chunk.chunk_id:03d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Chunk {chunk.chunk_id}\n")
            f.write(f"# Type: {chunk.section_type.value}\n")
            f.write(f"# Level: {chunk.chunk_level}\n")
            if chunk.is_large_chunk:
                f.write(f"# Large Chunk (refs: {chunk.large_chunk_reference_ids})\n")
            f.write(f"# Blurb: {chunk.blurb}\n")
            f.write(f"# Source: {chunk.source_document.semantic_identifier}\n")
            f.write("-" * 60 + "\n")
            f.write(chunk.content)
            f.write("\n")
            if chunk.doc_summary or chunk.chunk_context:
                f.write("\n" + "=" * 60 + "\n")
                if chunk.doc_summary:
                    f.write(f"# Doc Summary: {chunk.doc_summary[:200]}\n")
                if chunk.chunk_context:
                    f.write(f"# Chunk Context: {chunk.chunk_context[:200]}\n")
            if chunk.mini_chunk_texts:
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"# Mini-chunks ({len(chunk.mini_chunk_texts)} 个):\n")
                for i, mini in enumerate(chunk.mini_chunk_texts):
                    offset = chunk.mini_chunk_offsets[i] if chunk.mini_chunk_offsets else None
                    offset_str = f" [{offset[0]}:{offset[1]}]" if offset else ""
                    f.write(f"\n--- Mini {i}{offset_str} ---\n")
                    f.write(mini)
                    f.write("\n")

    for img_idx, (img_bytes, img_name) in enumerate(images):
        img_filename = f"image_{img_idx:03d}_{os.path.basename(img_name)}"
        with open(os.path.join(images_dir, img_filename), "wb") as f:
            f.write(img_bytes)

    print(f"\n[8] 结果已保存到: {output_dir}")
    print(f"    chunks.json: {len(chunks_data)} 个 chunk 元数据")
    print(f"    chunk_xxx.txt: {len(chunks)} 个文本文件")
    print(f"    images/: {len(images)} 张图片")
    if embeddings_data:
        print(f"    embeddings/: {len(embeddings_data)} 个 chunk 的向量文件")


def print_chunks(chunks: list[DocAwareChunk]) -> None:
    """打印分块结果摘要（含 mini-chunk 和 large chunk）"""
    normal_chunks = [c for c in chunks if not c.is_large_chunk]
    large_chunks = [c for c in chunks if c.is_large_chunk]
    text_chunks = [c for c in normal_chunks if c.section_type == SectionType.TEXT]
    image_chunks = [c for c in normal_chunks if c.section_type == SectionType.IMAGE]
    table_chunks = [c for c in normal_chunks if c.section_type == SectionType.TABULAR]

    total_mini = sum(
        len(c.mini_chunk_texts or []) for c in normal_chunks if c.mini_chunk_texts
    )
    total_with_ctx = sum(1 for c in normal_chunks if c.chunk_context)
    has_doc_summary = any(c.doc_summary for c in normal_chunks)

    print(f"\n{'='*70}")
    print("分块详情")
    print(f"{'='*70}")

    if text_chunks:
        print(f"\n--- 文本 Chunks ({len(text_chunks)} 个) ---")
        for chunk in text_chunks[:3]:
            mini_info = (
                f"[{len(chunk.mini_chunk_texts or [])} mini]"
                if chunk.mini_chunk_texts
                else ""
            )
            ctx_info = "[ctx]" if chunk.chunk_context else ""
            print(f"\n[Chunk {chunk.chunk_id}] (文本) {mini_info} {ctx_info}")
            print(f"  Blurb: {chunk.blurb[:80]}...")
            print(f"  长度: {len(chunk.content)} 字符")
            if chunk.chunk_context:
                print(f"  Context: {chunk.chunk_context[:80]}...")
            if chunk.mini_chunk_texts:
                for i, mini in enumerate(chunk.mini_chunk_texts[:2]):
                    print(f"    Mini {i}: {mini[:60]}...")
                if len(chunk.mini_chunk_texts) > 2:
                    print(f"    ... 还有 {len(chunk.mini_chunk_texts) - 2} 个 mini-chunk")
        if len(text_chunks) > 3:
            print(f"  ... 还有 {len(text_chunks) - 3} 个文本 chunk")

    if image_chunks:
        print(f"\n--- 图片 Chunks ({len(image_chunks)} 个) ---")
        for chunk in image_chunks[:2]:
            print(f"[Chunk {chunk.chunk_id}] Image: {chunk.image_file_id}")
        if len(image_chunks) > 2:
            print(f"  ... 还有 {len(image_chunks) - 2} 个图片 chunk")

    if table_chunks:
        print(f"\n--- 表格 Chunks ({len(table_chunks)} 个) ---")
        for chunk in table_chunks[:2]:
            print(f"[Chunk {chunk.chunk_id}] 表格: {chunk.content[:100]}...")
        if len(table_chunks) > 2:
            print(f"  ... 还有 {len(table_chunks) - 2} 个表格 chunk")

    if large_chunks:
        print(f"\n--- 大 Chunks ({len(large_chunks)} 个) ---")
        for chunk in large_chunks[:2]:
            print(f"[Chunk {chunk.chunk_id}] Large (refs: {chunk.large_chunk_reference_ids})")
            print(f"  长度: {len(chunk.content)} 字符")
        if len(large_chunks) > 2:
            print(f"  ... 还有 {len(large_chunks) - 2} 个大 chunk")

    # Embedding 统计
    embedded_chunks = [c for c in chunks if hasattr(c, "embeddings") and c.embeddings and c.embeddings.full_embedding]
    embedding_dim = len(embedded_chunks[0].embeddings.full_embedding) if embedded_chunks else 0
    total_mini_emb = sum(
        len(c.embeddings.mini_chunk_embeddings) for c in embedded_chunks if c.embeddings.mini_chunk_embeddings
    )

    print(f"\n{'='*70}")
    print("统计")
    print(f"{'='*70}")
    print(f"  标准 chunk 数: {len(normal_chunks)}")
    print(f"    - 文本: {len(text_chunks)}")
    print(f"    - 图片: {len(image_chunks)}")
    print(f"    - 表格: {len(table_chunks)}")
    print(f"  大 chunk 数: {len(large_chunks)}")
    print(f"  mini-chunk 总数: {total_mini}")
    print(f"  含上下文 chunk 数: {total_with_ctx}")
    print(f"  文档摘要: {'已生成' if has_doc_summary else '无'}")
    print(f"  嵌入 chunk 数: {len(embedded_chunks)}")
    if embedding_dim:
        print(f"  向量维度: {embedding_dim}")
        print(f"  mini-embedding 总数: {total_mini_emb}")
    print(f"  总 chunk 数: {len(chunks)}")
