"""图片处理器工厂（参考 embedding/factory.py）。"""

from __future__ import annotations

from image_processing.base import BaseImageProcessor
from image_processing.config import ImageProcessorConfig
from image_processing.local_processor import EasyOCRImageProcessor
from image_processing.remote_processor import OpenAIVisionProcessor


IMAGE_PROCESSOR_BACKENDS: dict[str, type[BaseImageProcessor]] = {
    "local": EasyOCRImageProcessor,
    "remote": OpenAIVisionProcessor,
}


def create_image_processor(
    backend: str | None = None,
    model_name: str | None = None,
    languages: list[str] | None = None,
    device: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    prompt: str | None = None,
) -> BaseImageProcessor:
    """根据配置创建图片处理器实例。

    配置优先级: 传入参数 > .env / 环境变量 > 硬编码默认值

    Args:
        backend: 后端类型，可选 "local" 或 "remote"
        model_name: 远程模型名称
        languages: 本地 OCR 语言列表
        device: 本地模型运行设备
        api_key: OpenAI API Key（仅 remote 后端需要）
        base_url: 远程模型 Base URL（兼容 OpenAI 的服务）
        prompt: 远程模型提示词

    Returns:
        BaseImageProcessor 实例
    """
    backend = (backend or ImageProcessorConfig.BACKEND).lower().strip()
    model_cls = IMAGE_PROCESSOR_BACKENDS.get(backend)
    if not model_cls:
        raise ValueError(
            f"不支持的图片处理后端 '{backend}'，"
            f"可选: {', '.join(IMAGE_PROCESSOR_BACKENDS.keys())}"
        )

    kwargs: dict = {}
    if backend == "local":
        if languages is not None:
            kwargs["languages"] = languages
        if device is not None:
            kwargs["device"] = device
    elif backend == "remote":
        if model_name is not None:
            kwargs["model_name"] = model_name
        if api_key is not None:
            kwargs["api_key"] = api_key
        if base_url is not None:
            kwargs["base_url"] = base_url
        if prompt is not None:
            kwargs["prompt"] = prompt

    return model_cls(**kwargs)
