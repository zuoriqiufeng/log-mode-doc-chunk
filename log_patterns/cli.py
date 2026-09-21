"""日志模式导入 CLI。"""

from __future__ import annotations

import argparse
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from log_patterns.importer import import_log_patterns


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导入结构化日志模式到 Qdrant 向量库"
    )
    parser.add_argument("file", help="日志模式文件路径（json/yaml/csv/xlsx/xls）")
    parser.add_argument(
        "--collection",
        dest="collection_name",
        help="目标 Qdrant collection，默认 log_patterns_collection",
    )
    parser.add_argument(
        "--qdrant-config",
        dest="qdrant_config_path",
        help="qdrant.yml 配置文件路径",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["openai", "local"],
        help="嵌入后端",
    )
    parser.add_argument(
        "--embedding-model",
        help="嵌入模型名称，如 BAAI/bge-large-zh-v1.5",
    )
    parser.add_argument(
        "--embedding-device",
        help="本地模型运行设备：cpu / cuda / cuda:0",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        help="嵌入批处理大小",
    )
    parser.add_argument(
        "--normalize-embeddings",
        action="store_true",
        help="对本地模型输出做 L2 归一化",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析分块，不嵌入不入库",
    )
    parser.add_argument(
        "--output-dir",
        help="dry-run 时输出 chunks.json 的目录",
    )
    parser.add_argument(
        "--document-id-prefix",
        default="log_pattern",
        help="生成 document_id 的前缀",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="以 JSON 美化格式输出结果",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[ERROR] 文件不存在: {args.file}", file=sys.stderr)
        return 1

    try:
        result = import_log_patterns(
            file_path=args.file,
            collection_name=args.collection_name,
            qdrant_config_path=args.qdrant_config_path,
            embedding_backend=args.embedding_backend,
            embedding_model=args.embedding_model,
            embedding_device=args.embedding_device,
            embedding_batch_size=args.embedding_batch_size,
            normalize_embeddings=args.normalize_embeddings,
            document_id_prefix=args.document_id_prefix,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
        )
    except Exception as e:
        print(f"[ERROR] 导入失败: {e}", file=sys.stderr)
        return 3

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))

    if result.get("invalid_patterns"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
