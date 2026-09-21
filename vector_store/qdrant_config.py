"""Qdrant 配置管理（从 qdrant.yml 读取）。"""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

# 未在 qdrant.yml / Web 配置中指定 collection_name 时使用的默认集合名。
# 各调用方统一引用此常量，避免默认值在多处字面量中漂移。
DEFAULT_COLLECTION_NAME = "chunk_collection"


@dataclass
class QdrantConfig:
    """Qdrant 连接与 Collection 配置。"""

    # 运行模式
    mode: str  # "local" | "remote"

    # 本地模式
    path: str | None = None

    # 远程模式
    host: str | None = None
    port: int | None = None
    grpc_port: int | None = None
    api_key: str | None = None
    https: bool = False

    # Collection 配置
    collection_name: str = DEFAULT_COLLECTION_NAME
    distance: str = "cosine"  # cosine | euclidean | dot
    vector_size: int = 1536
    auto_create_collection: bool = True

    # 写入批次大小（远程模式下单请求 payload 限制 32MB，减小批次可避免 400）
    upsert_batch_size: int = 100


def load_qdrant_config(config_path: str | None = None) -> QdrantConfig:
    """从 qdrant.yml 加载配置。

    Args:
        config_path: qdrant.yml 文件路径，默认从当前目录查找。

    Returns:
        QdrantConfig 实例。
    """
    if config_path is None:
        # 默认从当前工作目录或脚本所在目录查找
        candidates = [
            "qdrant.yml",
            os.path.join(os.path.dirname(__file__), "..", "qdrant.yml"),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                config_path = cand
                break

    if not config_path or not os.path.exists(config_path):
        # 回退到默认值
        return QdrantConfig(mode="local", path="./qdrant_data")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    mode = raw.get("mode", "local")

    return QdrantConfig(
        mode=mode,
        path=raw.get("path", "./qdrant_data") if mode == "local" else None,
        host=raw.get("host", "localhost") if mode == "remote" else None,
        port=raw.get("port", 6333) if mode == "remote" else None,
        grpc_port=raw.get("grpc_port") if mode == "remote" else None,
        api_key=raw.get("api_key") if mode == "remote" else None,
        https=raw.get("https", False) if mode == "remote" else False,
        collection_name=raw.get("collection_name", DEFAULT_COLLECTION_NAME),
        distance=raw.get("distance", "cosine"),
        vector_size=raw.get("vector_size", 1536),
        auto_create_collection=raw.get("auto_create_collection", True),
        upsert_batch_size=raw.get("upsert_batch_size", 100),
    )
