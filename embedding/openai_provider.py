"""OpenAI Embedding API 实现（参考自 Onyx CloudEmbedding）。

对应 Onyx:
    - backend/onyx/natural_language_processing/search_nlp_models.py
      中 CloudEmbedding._embed_openai() 方法
"""

from __future__ import annotations

import os

from embedding.base import BaseEmbeddingModel
from embedding.config import EmbeddingConfig
from embedding.models import Embedding


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    """OpenAI Embedding API 模型实现。

    通过 OpenAI Python SDK 直接调用 /v1/embeddings 端点。
    参考自 Onyx CloudEmbedding._embed_openai() 方法。
    """

    DEFAULT_MODEL = "text-embedding-3-small"
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        batch_size: int | None = None,
    ):
        self._api_key = api_key or EmbeddingConfig.OPENAI_API_KEY
        self._model_name = model_name or EmbeddingConfig.MODEL_NAME or self.DEFAULT_MODEL
        self._batch_size = batch_size or EmbeddingConfig.BATCH_SIZE or self.DEFAULT_BATCH_SIZE
        self._client = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise RuntimeError("openai 包未安装，请运行: pip install openai")
            if not self._api_key:
                raise RuntimeError(
                    "未配置 OpenAI API Key，请设置 OPENAI_API_KEY 环境变量或在 .env 中配置"
                )
            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def encode(self, texts: list[str]) -> list[Embedding]:
        if not texts:
            return []

        client = self._get_client()
        all_embeddings: list[Embedding] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            try:
                response = client.embeddings.create(
                    model=self._model_name,
                    input=batch,
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                raise RuntimeError(f"OpenAI Embedding API 调用失败: {e}")

        return all_embeddings
