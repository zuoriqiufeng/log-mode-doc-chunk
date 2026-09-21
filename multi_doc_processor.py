#!/usr/bin/env python3
"""
多格式文档处理与分块工具 — 主入口

支持格式: PDF, Word (.docx), Markdown (.md), HTML (.html), 纯文本 (.txt)

模块结构:
  models.py          — 数据模型 (SectionType, Section, Document, DocAwareChunk)
  extractors/        — 文档提取器 (PDF, DOCX, HTML, MD, TXT)
  chunking/          — 分块逻辑 (文本/图片/表格/大 chunk)
  embedding/         — 向量嵌入 (OpenAI / 本地模型)
  contextual_rag.py  — Contextual RAG 上下文增强
  pipeline.py        — 主处理流程
  utils.py           — 工具函数 (保存、打印、表格检测等)

参考 Onyx 项目代码:
- backend/onyx/file_processing/extract_file_text.py
- backend/onyx/file_processing/html_utils.py
- backend/onyx/indexing/chunker.py
- backend/onyx/indexing/chunking/document_chunker.py
- backend/onyx/connectors/models.py
- backend/onyx/indexing/indexing_pipeline.py
"""

from __future__ import annotations

import argparse
import os
import sys

# 自动加载项目根目录的 .env（如果存在）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_SCRIPT_DIR, ".env")
if os.path.exists(_ENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=False)
    except ImportError:
        pass

from extractors import EXTRACTOR_MAP
from pipeline import process_document
from utils import print_chunks, save_results


def _env_bool(key: str, default: bool = False) -> bool:
    """从环境变量读取布尔值（支持 true/1/yes/on）。"""
    val = os.environ.get(key, "").lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off", ""):
        return default
    return default


def main() -> int:
    parser = argparse.ArgumentParser(
        description="多格式文档处理与分块工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python multi_doc_processor.py document.md
  python multi_doc_processor.py doc.pdf output_dir --use-llm
  python multi_doc_processor.py file.docx out --no-contextual-rag
  python multi_doc_processor.py doc.md out --embed --embedding-backend openai
  python multi_doc_processor.py doc.md out --embed --embedding-backend local --embedding-model all-MiniLM-L6-v2
        """.strip(),
    )
    parser.add_argument("file", help="输入文件路径")
    parser.add_argument("output", nargs="?", default="chunks_output", help="输出目录（默认: chunks_output）")
    parser.add_argument(
        "--no-contextual-rag",
        dest="enable_contextual_rag",
        action="store_false",
        default=True,
        help="禁用 Contextual RAG 上下文增强",
    )
    parser.add_argument(
        "--use-llm",
        dest="use_llm",
        action="store_true",
        default=False,
        help="使用 OpenAI LLM 生成上下文（需配置 OPENAI_API_KEY）",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="标准 chunk 的 token 上限（默认: 512）",
    )
    parser.add_argument(
        "--mini-chunk-size",
        type=int,
        default=150,
        help="mini-chunk 的 token 上限（默认: 150）",
    )
    parser.add_argument(
        "--no-large-chunks",
        dest="enable_large_chunks",
        action="store_false",
        default=True,
        help="禁用大 chunk 生成",
    )
    parser.add_argument(
        "--embed",
        dest="enable_embedding",
        action="store_true",
        default=False,
        help="启用向量嵌入",
    )
    parser.add_argument(
        "--embedding-backend",
        type=str,
        default=os.environ.get("EMBEDDING_BACKEND", "openai"),
        choices=["openai", "local"],
        help="嵌入后端: openai (API) 或 local (本地模型, 默认从 .env 读取)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=os.environ.get("EMBEDDING_MODEL", None),
        help="嵌入模型名称 (默认从 .env 读取 EMBEDDING_MODEL)",
    )
    parser.add_argument(
        "--embedding-device",
        type=str,
        default=os.environ.get("LOCAL_EMBEDDING_DEVICE", None),
        help="本地模型运行设备 (默认从 .env 读取 LOCAL_EMBEDDING_DEVICE)",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=int(os.environ.get("EMBEDDING_BATCH_SIZE", 0)) or None,
        help="嵌入批处理大小 (默认从 .env 读取 EMBEDDING_BATCH_SIZE)",
    )
    parser.add_argument(
        "--normalize-embeddings",
        action="store_true",
        default=_env_bool("LOCAL_EMBEDDING_NORMALIZE", False),
        help="对本地模型输出进行 L2 归一化 (默认从 .env 读取 LOCAL_EMBEDDING_NORMALIZE)",
    )
    parser.add_argument(
        "--enable-vector-store",
        dest="enable_vector_store",
        action="store_true",
        default=False,
        help="将嵌入结果写入 Qdrant 向量数据库（需先配置 qdrant.yml）",
    )
    parser.add_argument(
        "--enrich",
        dest="enable_enrichment",
        action="store_true",
        default=_env_bool("ENABLE_ENRICHMENT", False),
        help="启用预富化：自动检测错误码/版本号等符号串并追加语义锚点",
    )
    parser.add_argument(
        "--enable-image-processing",
        dest="enable_image_processing",
        action="store_true",
        default=_env_bool("ENABLE_IMAGE_PROCESSING", False),
        help="启用图片处理（OCR / Vision），从图片中提取文本或描述",
    )
    parser.add_argument(
        "--image-processor-backend",
        type=str,
        default=os.environ.get("IMAGE_PROCESSOR_BACKEND", "local"),
        choices=["local", "remote"],
        help="图片处理后端: local (EasyOCR) 或 remote (OpenAI Vision)",
    )
    parser.add_argument(
        "--image-processor-model",
        type=str,
        default=os.environ.get("IMAGE_PROCESSOR_MODEL", None),
        help="远程图片处理模型名称 (默认从 .env 读取 IMAGE_PROCESSOR_MODEL)",
    )
    parser.add_argument(
        "--image-processor-base-url",
        type=str,
        default=os.environ.get("IMAGE_PROCESSOR_BASE_URL", None),
        help="远程图片处理 Base URL (默认从 .env 读取 IMAGE_PROCESSOR_BASE_URL，留空使用 OpenAI 官方地址)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"错误: 找不到文件 {args.file}")
        return 1

    document, chunks, images = process_document(
        args.file,
        args.output,
        chunk_token_limit=args.chunk_size,
        mini_chunk_size=args.mini_chunk_size,
        enable_large_chunks=args.enable_large_chunks,
        enable_contextual_rag=args.enable_contextual_rag,
        use_llm_for_contextual_rag=args.use_llm,
        enable_embedding=args.enable_embedding,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        embedding_device=args.embedding_device,
        embedding_batch_size=args.embedding_batch_size,
        normalize_embeddings=args.normalize_embeddings,
        enable_vector_store=args.enable_vector_store,
        enable_enrichment=args.enable_enrichment,
        enable_image_processing=args.enable_image_processing,
        image_processor_backend=args.image_processor_backend,
        image_processor_model=args.image_processor_model,
        image_processor_api_key=None,
        image_processor_base_url=args.image_processor_base_url,
    )
    print_chunks(chunks)
    save_results(chunks, images, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
