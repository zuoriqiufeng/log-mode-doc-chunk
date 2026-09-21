"""主处理流程：文档提取 → 段落构建 → 分块 → 大 chunk 生成 → 向量存储。"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from chunking.image import chunk_image_section
from chunking.large import generate_large_chunks
from chunking.tabular import chunk_tabular_section
from chunking.text import chunk_text_sections
from contextual_rag import add_contextual_rag
from embedding import create_embedding_model, Embedder
from extractors import get_extractor
from image_processing import (
    BaseImageProcessor,
    ImageCache,
    ImageProcessorConfig,
    build_image_chunk_text,
    create_image_processor,
)
from models import DocAwareChunk, Document, IndexChunk, Section, SectionType
from utils import detect_and_parse_table
from vector_store import create_vector_store


_EMBEDDED_IMAGE_RE = re.compile(r"【PIC:(\d+)】")


def _build_interleaved_body_sections(
    text: str,
    image_texts: list[str],
    image_file_ids: list[str],
) -> list[Section]:
    """按 [EMBEDDED_IMAGE:index] 占位符将文本和图片交叉构建为 Section 列表。"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sections: list[Section] = []

    for para in paragraphs:
        parts = _EMBEDDED_IMAGE_RE.split(para)
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # 文本段
                stripped = part.strip()
                if stripped:
                    sections.append(Section(type=SectionType.TEXT, text=stripped))
            else:
                # 图片占位符索引
                try:
                    idx = int(part)
                except ValueError:
                    continue
                if 0 <= idx < len(image_texts):
                    sections.append(
                        Section(
                            type=SectionType.IMAGE,
                            text=image_texts[idx],
                            image_file_id=image_file_ids[idx],
                        )
                    )

    return sections


def process_document(
    file_path: str,
    output_dir: str,
    chunk_token_limit: int = 512,
    mini_chunk_size: int = 150,
    enable_large_chunks: bool = True,
    large_chunk_ratio: int = 4,
    enable_contextual_rag: bool = True,
    use_llm_for_contextual_rag: bool = False,
    enable_embedding: bool = False,
    embedding_backend: str = "openai",
    embedding_model: str | None = None,
    embedding_device: str | None = None,
    embedding_batch_size: int | None = None,
    normalize_embeddings: bool = False,
    enable_vector_store: bool = False,
    enable_enrichment: bool = False,
    enable_image_processing: bool | None = None,
    image_processor_backend: str | None = None,
    image_processor_model: str | None = None,
    image_processor_api_key: str | None = None,
    image_processor_base_url: str | None = None,
) -> tuple[Document, list[DocAwareChunk], list[tuple[bytes, str]]]:
    """处理任意支持的文档类型：提取内容并分块（支持 mini-chunk 和 large chunk）。"""

    print(f"\n{'='*70}")
    print(f"处理文件: {file_path}")
    print(f"{'='*70}")

    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 初始化图片处理器（本地 OCR 或远程 Vision）
    image_processing_enabled = (
        ImageProcessorConfig.ENABLED
        if enable_image_processing is None
        else enable_image_processing
    )
    image_processor: BaseImageProcessor | None = None
    image_cache: ImageCache | None = None

    if image_processing_enabled:
        try:
            image_processor = create_image_processor(
                backend=image_processor_backend,
                model_name=image_processor_model,
                api_key=image_processor_api_key,
                base_url=image_processor_base_url,
            )
            image_cache = ImageCache()
            print(f"\n[0] 图片处理已启用，后端: {image_processor.backend_name}")
        except Exception as e:
            print(f"\n[WARN] 图片处理器初始化失败: {e}")

    # 1. 获取提取器并提取内容
    extractor = get_extractor(file_path)
    text, metadata, images = extractor.extract(file_path)

    ext = os.path.splitext(file_path)[1].lower()
    print(f"\n[1] 文档提取完成 ({ext})")
    print(f"    使用提取器: {extractor.__class__.__name__}")
    print(f"    文本长度: {len(text)} 字符")
    print(f"    提取图片数: {len(images)}")
    if metadata:
        print(f"    元数据: {json.dumps(metadata, ensure_ascii=False, indent=2)}")

    # 2. 保存图片（串行本地 IO）+ 可选图片处理（远程 vision 并发）
    image_processed_texts: list[str] = []
    image_file_ids: list[str] = []

    # 2.1 串行：保存文件并分配下标（文件名依赖 img_idx，须先落定）
    saved_images: list[tuple[int, bytes, str, str]] = []
    for img_idx, (img_bytes, img_name) in enumerate(images):
        img_filename = f"image_{img_idx:03d}_{os.path.basename(img_name)}"
        img_path = os.path.join(images_dir, img_filename)
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        print(f"    图片已保存: {img_path} ({len(img_bytes)} bytes)")
        saved_images.append((img_idx, img_bytes, img_name, img_path))

    def _process_one_image(item: tuple[int, bytes, str, str]) -> str:
        """处理单张图片（缓存命中直接返回），返回 section 文本。"""
        _idx, img_bytes, img_name, _img_path = item
        if not (image_processor and image_cache):
            return build_image_chunk_text(img_name, "")
        cached = image_cache.get(img_bytes, image_processor)
        if cached is not None:
            processed_text = cached
        else:
            processed_text = image_processor.process(img_bytes, img_name)
            # 仅成功结果写缓存：失败（空串）不落盘，便于调参后重试
            if processed_text:
                image_cache.set(img_bytes, image_processor, processed_text)
        return build_image_chunk_text(img_name, processed_text)

    # 2.2 处理并按下标保序组装（【PIC:n】占位符依赖 image_texts[idx] 对齐）
    if saved_images:
        # 仅远程 vision 并发；本地 EasyOCR reader 共享实例不做并发
        remote_vision = (
            image_processor is not None and image_processor.backend_name == "openai_vision"
        )
        image_concurrency = int(os.environ.get("IMAGE_CONCURRENCY", "6"))
        workers = (
            max(1, min(image_concurrency, len(saved_images))) if remote_vision else 1
        )
        results: dict[int, str] = {}
        if workers > 1:
            print(f"    图片处理并发: {workers} 路")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # pool.map 保序；再按 idx 落字典双保险。
                # 注意：循环变量严禁叫 text——会覆盖外层文档正文 text！
                for item, section_text in zip(saved_images, pool.map(_process_one_image, saved_images)):
                    results[item[0]] = section_text
        else:
            for item in saved_images:
                results[item[0]] = _process_one_image(item)
        for img_idx, _b, _n, img_path in saved_images:
            image_processed_texts.append(results[img_idx])
            image_file_ids.append(img_path)

    # 3. 检测表格
    table_result = detect_and_parse_table(text)
    table_sections: list[Section] = []

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

    # 4. 构建文本段落
    text_without_table = text
    if table_result:
        heading, csv_text = table_result
        table_lines_set = set(line.strip() for line in csv_text.strip().splitlines())
        remaining_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in table_lines_set or stripped == heading:
                continue
            remaining_lines.append(line)
        text_without_table = "\n".join(remaining_lines)

    text_sections = _build_interleaved_body_sections(
        text_without_table,
        image_processed_texts,
        image_file_ids,
    )
    image_sections = [s for s in text_sections if s.type == SectionType.IMAGE]

    # 4.5. 预富化 — 检测原始文本中的符号串，生成标注块作为独立 Section
    if enable_enrichment:
        from enrichment import detect_annotations, enrich_document_text
        annotations = detect_annotations(text)
        if annotations:
            print(f"\n[4.5] 预富化完成: 检测到 {len(annotations)} 个符号串")
            for a in annotations:
                print(f"      [{a.type}] {a.raw[:60]:<60} → {a.enriched}")
            enriched_block = enrich_document_text("", annotations)
            text_sections.append(Section(type=SectionType.TEXT, text=enriched_block))
        else:
            print(f"\n[4.5] 预富化: 未检测到符号串")

    # 5. 构建 Document
    all_sections = text_sections + image_sections + table_sections
    document = Document(
        id=file_path,
        semantic_identifier=file_path,
        sections=all_sections,
        title=metadata.get("Title") or os.path.basename(file_path),
        metadata=metadata,
    )

    print(f"\n[3] 构建 Document 对象")
    print(f"    ID: {document.id}")
    print(f"    标题: {document.title}")
    print(f"    总段落数: {len(document.sections)}")
    print(f"      - 文本段落: {len(text_sections)}")
    print(f"      - 图片段落: {len(image_sections)}")
    print(f"      - 表格段落: {len(table_sections)}")

    # 6. 分块（标准 chunk + mini-chunk）
    print(f"\n[4] 开始分块")
    print(f"    chunk_token_limit={chunk_token_limit}, mini_chunk_size={mini_chunk_size}")
    all_chunks: list[DocAwareChunk] = []
    chunk_id = 0

    text_chunks = chunk_text_sections(
        text_sections,
        document,
        chunk_token_limit,
        chunk_id_start=chunk_id,
        mini_chunk_size=mini_chunk_size,
    )
    for c in text_chunks:
        c.chunk_id = chunk_id
        all_chunks.append(c)
        chunk_id += 1

    for section in image_sections:
        chunk = chunk_image_section(section)
        if chunk:
            chunk.source_document = document
            chunk.chunk_id = chunk_id
            all_chunks.append(chunk)
            chunk_id += 1

    for section in table_sections:
        tabular_chunks = chunk_tabular_section(section, chunk_id_start=chunk_id)
        for c in tabular_chunks:
            c.source_document = document
            all_chunks.append(c)
            chunk_id += 1

    # 7. 生成大 chunks（multipass 模式）
    if enable_large_chunks:
        large_chunks = generate_large_chunks(
            all_chunks, ratio=large_chunk_ratio, chunk_id_start=chunk_id
        )
        if large_chunks:
            for lc in large_chunks:
                lc.chunk_id = chunk_id
                all_chunks.append(lc)
                chunk_id += 1

    # Mini-chunk 统计
    total_mini = sum(
        len(c.mini_chunk_texts or [])
        for c in all_chunks
        if c.mini_chunk_texts
    )

    # 4.6. 预富化 payload 侧：按 chunk 检测标注，写入 keywords / data_types。
    # 与 4.5 的文本标注块互补：文本块供 BGE 编码，payload 供关键词兜底与类型过滤。
    if enable_enrichment:
        from enrichment import detect_annotations

        kw_chunks = 0
        kw_minis = 0
        for c in all_chunks:
            annotations = detect_annotations(c.content)
            if annotations:
                c.custom_payload["keywords"] = [a.enriched for a in annotations]
                c.custom_payload["data_types"] = sorted({a.type for a in annotations})
                kw_chunks += 1

            if c.mini_chunk_texts and not c.mini_chunk_payloads:
                mini_payloads: list[dict] = []
                for mini_text in c.mini_chunk_texts:
                    mini_annotations = detect_annotations(mini_text)
                    if mini_annotations:
                        mini_payloads.append({
                            "keywords": [a.enriched for a in mini_annotations],
                            "data_types": sorted({a.type for a in mini_annotations}),
                        })
                        kw_minis += 1
                    else:
                        mini_payloads.append({})
                c.mini_chunk_payloads = mini_payloads

        print("\n[4.6] 富化 payload 侧完成")
        print(f"    携带 keywords/data_types 的 chunk: {kw_chunks}")
        print(f"    携带 keywords/data_types 的 mini-chunk: {kw_minis}")

    # 8. Contextual RAG 上下文增强
    if enable_contextual_rag:
        print(f"\n[5] Contextual RAG 上下文增强")
        if use_llm_for_contextual_rag:
            print("    模式: LLM (OpenAI)")
        else:
            print("    模式: 基于规则（无需 LLM）")
        all_chunks = add_contextual_rag(
            all_chunks,
            use_llm=use_llm_for_contextual_rag,
        )
        # 统计有多少 chunk 获得了上下文
        with_context = sum(1 for c in all_chunks if c.chunk_context)
        print(f"    已添加上下文 chunk 数: {with_context}")

    # 9. 向量嵌入
    if enable_embedding:
        print(f"\n[6] 向量嵌入")
        model = create_embedding_model(
            backend=embedding_backend,
            model_name=embedding_model,
            device=embedding_device,
            batch_size=embedding_batch_size,
            normalize_embeddings=normalize_embeddings,
        )
        embedder = Embedder(embedding_model=model)
        all_chunks = embedder.embed_chunks(all_chunks)
        print(f"    嵌入完成: {len(all_chunks)} 个 chunk")
        # 统计 embedding 信息
        if all_chunks and hasattr(all_chunks[0], "embeddings"):
            first = all_chunks[0]
            dim = len(first.embeddings.full_embedding) if first.embeddings.full_embedding else 0
            mini_count = len(first.embeddings.mini_chunk_embeddings) if first.embeddings.mini_chunk_embeddings else 0
            print(f"    向量维度: {dim}")
            print(f"    首个 chunk mini-embeddings: {mini_count}")

    # 10. 写入向量数据库
    if enable_vector_store and enable_embedding:
        print(f"\n[7] 向量数据库写入 (Qdrant)")
        store = create_vector_store()
        index_chunks = [c for c in all_chunks if isinstance(c, IndexChunk)]
        if index_chunks:
            store.upsert_chunks(index_chunks)
            print(f"    已写入 {len(index_chunks)} 个 chunk")
            print(f"    Collection: {store.collection_name}")
            print(f"    总数量: {store.get_chunk_count()}")
        else:
            raise RuntimeError("没有 IndexChunk 可供写入")

    print(f"\n[8] 分块完成")
    print(f"    标准 chunk 数: {len([c for c in all_chunks if not c.is_large_chunk])}")
    print(f"      - 文本 chunks: {len([c for c in all_chunks if c.section_type == SectionType.TEXT and not c.is_large_chunk])}")
    print(f"      - 图片 chunks: {len([c for c in all_chunks if c.section_type == SectionType.IMAGE and not c.is_large_chunk])}")
    print(f"      - 表格 chunks: {len([c for c in all_chunks if c.section_type == SectionType.TABULAR and not c.is_large_chunk])}")
    print(f"    大 chunks: {len([c for c in all_chunks if c.is_large_chunk])}")
    print(f"    mini-chunks 总数: {total_mini}")

    return document, all_chunks, images