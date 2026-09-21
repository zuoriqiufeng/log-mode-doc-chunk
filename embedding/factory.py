"""嵌入模型工厂（参考自 Onyx 配置驱动工厂模式）。

对应 Onyx:
    - backend/onyx/natural_language_processing/search_nlp_models.py
      中 EmbeddingModel.__init__ 的 provider_type 路由逻辑
    - backend/onyx/indexing/embedder.py
      中 DefaultIndexingEmbedder.from_db_search_settings() 工厂方法
"""

from __future__ import annotations

import threading

from embedding.base import BaseEmbeddingModel
from embedding.config import EmbeddingConfig
from embedding.local_provider import LocalEmbeddingModel
from embedding.openai_provider import OpenAIEmbeddingModel


EMBEDDING_BACKENDS: dict[str, type[BaseEmbeddingModel]] = {
    "openai": OpenAIEmbeddingModel,
    "local": LocalEmbeddingModel,
}

# 单例缓存：相同配置共享同一实例，避免每文件/每请求重载大模型
_MODEL_CACHE: dict[tuple, BaseEmbeddingModel] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def create_embedding_model(
    backend: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    device: str | None = None,
    batch_size: int | None = None,
    normalize_embeddings: bool | None = None,
) -> BaseEmbeddingModel:
    """根据配置创建嵌入模型实例。

    配置优先级: 传入参数 > .env / 环境变量 > 硬编码默认值

    Args:
        backend: 模型后端类型，可选 "openai" 或 "local"
        model_name: 模型名称
        api_key: OpenAI API Key（仅 openai 后端需要）
        device: 本地模型运行设备（仅 local 后端需要）
        batch_size: 批处理大小
        normalize_embeddings: 是否 L2 归一化（仅 local 后端）

    Returns:
        BaseEmbeddingModel 实例

    Raises:
        ValueError: 不支持的后端类型
    """
    backend = (backend or EmbeddingConfig.BACKEND).lower().strip()
    model_cls = EMBEDDING_BACKENDS.get(backend)
    if not model_cls:
        raise ValueError(
            f"不支持的嵌入后端 '{backend}'，"
            f"可选: {', '.join(EMBEDDING_BACKENDS.keys())}"
        )

    kwargs: dict = {}
    if model_name is not None:
        kwargs["model_name"] = model_name
    if batch_size is not None:
        kwargs["batch_size"] = batch_size

    if backend == "openai":
        if api_key is not None:
            kwargs["api_key"] = api_key
    elif backend == "local":
        if device is not None:
            kwargs["device"] = device
        if normalize_embeddings is not None:
            kwargs["normalize_embeddings"] = normalize_embeddings

    # 单例复用：同配置返回同一实例（pipeline 每文件与 /api/query 等每请求共享）
    cache_key = (backend, tuple(sorted(kwargs.items())))
    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            model = model_cls(**kwargs)
            _MODEL_CACHE[cache_key] = model
        return model
