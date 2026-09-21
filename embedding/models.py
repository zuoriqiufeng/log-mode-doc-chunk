"""向量嵌入数据模型（参考自 Onyx shared_configs/model_server_models.py）。"""

from __future__ import annotations

from dataclasses import dataclass

# Embedding 类型别名：一维浮点向量
Embedding = list[float]


@dataclass
class EmbedRequest:
    """嵌入请求模型（参考自 Onyx EmbedRequest）。"""

    texts: list[str]
    model_name: str | None = None
    normalize_embeddings: bool = False


@dataclass
class EmbedResponse:
    """嵌入响应模型（参考自 Onyx EmbedResponse）。"""

    embeddings: list[Embedding]
