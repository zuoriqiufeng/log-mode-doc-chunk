"""日志模式导入编排：解析 → 分块 → 嵌入 → 写入向量库。"""

from __future__ import annotations

import json
import os
from typing import Any

from embedding import create_embedding_model, Embedder
from embedding.config import EmbeddingConfig
from log_patterns.chunker import LogPatternChunker
from log_patterns.models import LogPattern
from log_patterns.parsers import get_parser
from models import IndexChunk
from vector_store.qdrant_config import load_qdrant_config, QdrantConfig
from vector_store.qdrant_store import QdrantVectorStore


DEFAULT_COLLECTION_NAME = "log_patterns_collection"


def _resolve_collection_name(
    collection_name: str | None,
    qdrant_config_path: str | None = None,
) -> str:
    """解析日志模式目标 collection。

    优先级：显式参数 > LOG_PATTERN_COLLECTION_NAME 环境变量 > 默认独立集合。
    不复用 qdrant.yml 中的 collection_name（那是文档库的配置），避免日志模式
    写入文档集合造成污染。
    """
    if collection_name:
        return collection_name
    env_name = os.environ.get("LOG_PATTERN_COLLECTION_NAME", "").strip()
    if env_name:
        return env_name
    return DEFAULT_COLLECTION_NAME


def _build_qdrant_config(
    collection_name: str | None = None,
    qdrant_config_path: str | None = None,
) -> QdrantConfig:
    """构建 QdrantConfig，允许覆盖 collection 名称。"""
    config = load_qdrant_config(qdrant_config_path)
    config.collection_name = _resolve_collection_name(collection_name, qdrant_config_path)
    return config


def _embedding_params_from_config() -> dict[str, Any]:
    """从 EmbeddingConfig / .env 读取默认嵌入参数。"""
    return {
        "backend": EmbeddingConfig.BACKEND,
        "model_name": EmbeddingConfig.MODEL_NAME,
        "device": EmbeddingConfig.LOCAL_DEVICE,
        "batch_size": EmbeddingConfig.BATCH_SIZE or 32,
        "normalize_embeddings": EmbeddingConfig.LOCAL_NORMALIZE,
    }


def import_log_patterns(
    file_path: str,
    *,
    collection_name: str | None = None,
    embedding_backend: str | None = None,
    embedding_model: str | None = None,
    embedding_device: str | None = None,
    embedding_batch_size: int | None = None,
    normalize_embeddings: bool | None = None,
    qdrant_config_path: str | None = None,
    document_id_prefix: str = "log_pattern",
    dry_run: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """导入日志模式文件到 Qdrant。

    Args:
        file_path: 日志模式文件路径（json/yaml/csv/xlsx/xls）
        collection_name: 目标 Qdrant collection，默认 log_patterns_collection
        embedding_backend: openai / local
        embedding_model: 模型名称
        embedding_device: cpu / cuda
        embedding_batch_size: 批大小
        normalize_embeddings: 是否 L2 归一化
        qdrant_config_path: qdrant.yml 路径
        document_id_prefix: 生成的 document_id 前缀
        dry_run: 为 True 时不嵌入/不入库，仅解析分块
        output_dir: dry_run 时输出 chunks.json 的目录

    Returns:
        导入结果摘要
    """
    # 1. 解析
    parser = get_parser(file_path)
    patterns = parser.parse(file_path)

    # 校验
    validation_errors: list[dict[str, Any]] = []
    valid_patterns: list[LogPattern] = []
    for pattern in patterns:
        errors = pattern.validate()
        if errors:
            validation_errors.append(
                {"pattern_id": pattern.pattern_id, "errors": errors}
            )
        else:
            valid_patterns.append(pattern)

    # 2. 分块
    chunker = LogPatternChunker(document_id_prefix=document_id_prefix)
    chunks = chunker.chunk(valid_patterns)

    result: dict[str, Any] = {
        "status": "parsed",
        "file_path": file_path,
        "patterns": len(patterns),
        "valid_patterns": len(valid_patterns),
        "invalid_patterns": len(validation_errors),
        "standard_chunks": len(chunks),
        "mini_chunks": sum(len(c.mini_chunk_texts or []) for c in chunks),
        "collection": _resolve_collection_name(collection_name, qdrant_config_path),
        "validation_errors": validation_errors,
        "dry_run": dry_run,
    }

    if dry_run:
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            summary = []
            for c in chunks:
                summary.append(
                    {
                        "pattern_id": c.source_document.id,
                        "chunk_id": c.chunk_id,
                        "content": c.content,
                        "mini_chunk_texts": c.mini_chunk_texts,
                        "custom_payload": c.custom_payload,
                        "mini_chunk_payloads": c.mini_chunk_payloads,
                    }
                )
            out_path = os.path.join(output_dir, "chunks.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            result["dry_run_output"] = out_path
        return result

    if not chunks:
        result["status"] = "no_valid_patterns"
        return result

    # 3. 嵌入
    embed_defaults = _embedding_params_from_config()
    model = create_embedding_model(
        backend=embedding_backend or embed_defaults["backend"],
        model_name=embedding_model or embed_defaults["model_name"],
        device=embedding_device or embed_defaults["device"],
        batch_size=embedding_batch_size or embed_defaults["batch_size"],
        normalize_embeddings=(
            normalize_embeddings
            if normalize_embeddings is not None
            else embed_defaults["normalize_embeddings"]
        ),
    )
    embedder = Embedder(embedding_model=model)
    index_chunks = embedder.embed_chunks(chunks)

    # 4. 写入 Qdrant
    qconf = _build_qdrant_config(collection_name, qdrant_config_path)
    store = QdrantVectorStore(config=qconf)
    try:
        store.upsert_chunks(index_chunks)
        result.update(
            {
                "status": "imported",
                "collection": store.collection_name,
                "total_points": store.get_chunk_count(),
            }
        )
    finally:
        try:
            store._client.close()
        except Exception:
            pass

    return result


def import_log_patterns_from_data(
    patterns_data: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """从内存中的 JSON 对象列表导入日志模式。

    通过写临时文件复用解析/分块/入库逻辑。
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as f:
        json.dump(patterns_data, f, ensure_ascii=False)
        tmp_path = f.name

    try:
        return import_log_patterns(tmp_path, **kwargs)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
