"""图片处理配置管理（参考 embedding/config.py）。"""

from __future__ import annotations

import os

# 自动加载 .env
_module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_module_dir, ".env")
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


def _env_list(key: str, default: list[str] | None = None) -> list[str]:
    """从环境变量读取逗号分隔列表。"""
    raw = os.environ.get(key, "")
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


class ImageProcessorConfig:
    """图片处理配置。"""

    # 总开关
    ENABLED: bool = _env_bool("ENABLE_IMAGE_PROCESSING", False)

    # 后端: local | remote
    BACKEND: str = os.environ.get("IMAGE_PROCESSOR_BACKEND", "local")

    # 远程模型名称（仅 remote 后端使用）
    MODEL_NAME: str = os.environ.get("IMAGE_PROCESSOR_MODEL", "gpt-4o-mini")

    # 远程模型 API Key（默认回退到 OPENAI_API_KEY）
    API_KEY: str = os.environ.get("IMAGE_PROCESSOR_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

    # 远程模型 Base URL（为空使用 OpenAI 官方地址，可填兼容服务地址如 vLLM/Ollama）
    BASE_URL: str | None = os.environ.get("IMAGE_PROCESSOR_BASE_URL") or None

    # 本地 OCR 语言列表
    OCR_LANGUAGES: list[str] = _env_list("OCR_LANGUAGES", ["ch_sim", "en"])

    # 本地模型运行设备: cpu | cuda
    OCR_DEVICE: str = os.environ.get("OCR_DEVICE", "cpu")

    # 缓存目录
    CACHE_DIR: str = os.environ.get("IMAGE_CACHE_DIR", ".image_cache")

    # 过小图片跳过处理
    MIN_IMAGE_WIDTH: int = _env_int("IMAGE_MIN_WIDTH", 10)
    MIN_IMAGE_HEIGHT: int = _env_int("IMAGE_MIN_HEIGHT", 10)

    # 远程模型提示词
    REMOTE_PROMPT: str = os.environ.get(
        "IMAGE_PROCESSOR_PROMPT",
        "请提取图片中的文字内容，并用一句话简要描述图片内容。"
        "如果图片中没有文字，只描述内容即可。"
        "输出格式要求：第一行以 [图片内容] 开头，第二行以 [图片文字] 开头。",
    )
