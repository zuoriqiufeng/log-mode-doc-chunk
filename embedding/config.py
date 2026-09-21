"""配置管理（参考自 Onyx 配置架构）。

集中管理所有嵌入相关的环境变量配置，避免在各模块中散落 os.environ.get。

配置优先级:
    1. 显式传入参数
    2. 环境变量
    3. .env 文件
    4. 硬编码默认值
"""

from __future__ import annotations

import os

# 自动加载 .env
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=False)
    except ImportError:
        pass


def _env_bool(key: str, default: bool = False) -> bool:
    """从环境变量读取布尔值。"""
    val = os.environ.get(key, "").lower()
    return val in ("true", "1", "yes", "on")


def _env_int(key: str, default: int) -> int:
    """从环境变量读取整数。"""
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


class EmbeddingConfig:
    """嵌入模型配置（参考自 Onyx SearchSettings）。"""

    # 后端选择
    BACKEND: str = os.environ.get("EMBEDDING_BACKEND", "openai")

    # 模型名称
    MODEL_NAME: str | None = os.environ.get("EMBEDDING_MODEL") or None

    # 批处理大小
    BATCH_SIZE: int | None = _env_int("EMBEDDING_BATCH_SIZE", 0) or None

    # --- OpenAI 专用 ---
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # --- 本地模型专用 ---
    LOCAL_DEVICE: str = os.environ.get("LOCAL_EMBEDDING_DEVICE", "cpu")
    LOCAL_NORMALIZE: bool = _env_bool("LOCAL_EMBEDDING_NORMALIZE", False)

    # --- HuggingFace 下载配置 ---
    HF_ENDPOINT: str = os.environ.get("HF_ENDPOINT", "")
    HF_HOME: str = os.environ.get("HF_HOME", "")
