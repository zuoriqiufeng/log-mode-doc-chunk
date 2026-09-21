"""本地 sentence-transformers 模型实现（参考自 Onyx model_server/encoders.py）。

对应 Onyx:
    - backend/model_server/encoders.py
      中 FastAPI 端点 /encoder/bi-encoder-embed 的本地推理逻辑
"""

from __future__ import annotations

import os
import threading

from embedding.base import BaseEmbeddingModel
from embedding.config import EmbeddingConfig
from embedding.models import Embedding


class LocalEmbeddingModel(BaseEmbeddingModel):
    """本地 sentence-transformers 模型实现。

    直接加载 Hugging Face 模型并在本地推理，无需外部 API。
    首次使用时会自动下载模型到本地缓存目录。

    支持模型示例:
        - "all-MiniLM-L6-v2" (默认, 384维)
        - "BAAI/bge-large-zh-v1.5" (中文, 1024维)
        - "sentence-transformers/all-mpnet-base-v2" (768维)

    参考自 Onyx model_server/encoders.py 中的本地编码逻辑。
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    DEFAULT_BATCH_SIZE = 32

    # 模块级注入：确保 HF_HOME / HF_ENDPOINT 在进程环境里
    _hf_home = EmbeddingConfig.HF_HOME
    _hf_endpoint = EmbeddingConfig.HF_ENDPOINT
    if _hf_home:
        os.environ.setdefault("HF_HOME", _hf_home)
    if _hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", _hf_endpoint)

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
        normalize_embeddings: bool | None = None,
    ):
        self._model_name = model_name or EmbeddingConfig.MODEL_NAME or self.DEFAULT_MODEL
        self._device = device or EmbeddingConfig.LOCAL_DEVICE
        self._batch_size = batch_size or EmbeddingConfig.BATCH_SIZE or self.DEFAULT_BATCH_SIZE

        if normalize_embeddings is None:
            self._normalize_embeddings = EmbeddingConfig.LOCAL_NORMALIZE
        else:
            self._normalize_embeddings = normalize_embeddings

        self._model = None
        # RLock：加载与推理互斥，且 encode 内可重入调用 _get_model
        self._lock = threading.RLock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:  # 双检锁，防并发首次双载
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError:
                        raise RuntimeError(
                            "sentence-transformers 包未安装，请运行: "
                            "pip install sentence-transformers"
                        )
                    # 优先本地加载，不存在时自动从 HF_ENDPOINT 下载（镜像优先）
                    print(f"    加载本地模型: {self._model_name} (device={self._device})")
                    self._model = SentenceTransformer(
                        self._model_name,
                        device=self._device,
                    )
        return self._model

    def encode(self, texts: list[str]) -> list[Embedding]:
        if not texts:
            return []

        with self._lock:  # 多文件并发时共享同一实例，加载+推理串行
            model = self._get_model()
            try:
                embeddings = model.encode(
                    texts,
                    batch_size=self._batch_size,
                    show_progress_bar=False,
                    normalize_embeddings=self._normalize_embeddings,
                    convert_to_numpy=True,
                )
                return embeddings.tolist()
            except Exception as e:
                raise RuntimeError(f"本地模型嵌入失败: {e}")
