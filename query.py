#!/usr/bin/env python3
"""向量查询工具 — 支持 mini-chunk 搜索，返回 large chunk 拼接内容。

使用示例:
  python query.py "如何配置数据库节点"
  python query.py "i2Stream 同步规则" --top-k 5
  python query.py "OceanBase 数据库" --filter document_id=word/3.docx
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

from embedding import create_embedding_model
from vector_store import create_vector_store
from vector_store.searcher import Searcher


def main() -> int:
    parser = argparse.ArgumentParser(
        description="向量查询工具 — 支持 mini-chunk 搜索，返回 large chunk 拼接内容",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python query.py "如何配置数据库节点"
  python query.py "i2Stream 同步规则" --top-k 5
  python query.py "OceanBase 数据库" --filter document_id=word/3.docx
        """.strip(),
    )
    parser.add_argument("query", help="查询文本")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回结果数量上限（默认: 5）",
    )
    parser.add_argument(
        "--embedding-backend",
        type=str,
        default=os.environ.get("EMBEDDING_BACKEND", "local"),
        choices=["openai", "local"],
        help="嵌入后端（默认从 .env 读取）",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=os.environ.get("EMBEDDING_MODEL", None),
        help="嵌入模型名称（默认从 .env 读取）",
    )
    parser.add_argument(
        "--embedding-device",
        type=str,
        default=os.environ.get("LOCAL_EMBEDDING_DEVICE", None),
        help="本地模型设备",
    )
    parser.add_argument(
        "--normalize-embeddings",
        action="store_true",
        default=False,
        help="L2 归一化",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="过滤条件，格式: key=value（如 document_id=word/3.docx）",
    )

    args = parser.parse_args()

    # 1. 初始化向量存储
    print("[1] 初始化向量存储...")
    store = create_vector_store()
    print(f"    Collection: {store.collection_name}")
    print(f"    总 chunk 数: {store.get_chunk_count()}")

    if store.get_chunk_count() == 0:
        print("    [ERROR] 向量数据库为空，请先运行文档处理流程写入数据")
        return 1

    # 2. 初始化嵌入模型
    print(f"\n[2] 加载嵌入模型: {args.embedding_model or 'default'}")
    model = create_embedding_model(
        backend=args.embedding_backend,
        model_name=args.embedding_model,
        device=args.embedding_device,
        normalize_embeddings=args.normalize_embeddings,
    )
    print(f"    模型: {model.model_name}")

    # 3. 初始化搜索器
    searcher = Searcher(vector_store=store, embedding_model=model)

    # 4. 解析过滤条件
    filters = None
    if args.filter:
        try:
            key, value = args.filter.split("=", 1)
            filters = {key.strip(): value.strip()}
            print(f"\n[3] 过滤条件: {filters}")
        except ValueError:
            print("    [ERROR] 过滤条件格式错误，应为 key=value")
            return 1

    # 5. 执行搜索
    print(f"\n[4] 查询: \"{args.query}\"")
    print(f"    top_k={args.top_k}")
    print("=" * 70)

    results = searcher.search(
        query=args.query,
        top_k=args.top_k,
        filters=filters,
    )

    if not results:
        print("未找到匹配结果")
        return 0

    # 6. 输出结果
    for idx, r in enumerate(results, 1):
        print(f"\n--- 结果 {idx} (score={r.score:.4f}) ---")
        print(f"文档: {r.document_id}")
        print(f"标题: {r.title}")
        print(f"类型: {r.chunk_level}"
              f"{' (Large Chunk)' if r.is_large_chunk else ''}")
        if r.is_large_chunk and r.source_chunk_ids:
            print(f"包含标准 chunk: {r.source_chunk_ids}")
        print(f"\n内容:")
        content = r.content.strip()
        if len(content) > 2000:
            print(content[:2000])
            print(f"\n... (共 {len(content)} 字符，已截断)")
        else:
            print(content)
        print("-" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
