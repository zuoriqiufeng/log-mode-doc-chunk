"""图片处理抽象基类。"""

from __future__ import annotations

import abc


class BaseImageProcessor(abc.ABC):
    """图片处理器抽象基类。

    实现类接收图片二进制数据，返回可用于文本嵌入和检索的字符串描述。
    典型实现包括：
      - 本地 OCR（如 EasyOCR）
      - 远程多模态模型（如 OpenAI Vision）
    """

    @abc.abstractmethod
    def process(self, image_bytes: bytes, filename: str = "") -> str:
        """处理单张图片。

        Args:
            image_bytes: 图片文件二进制数据。
            filename: 原始文件名，仅用于日志或提示。

        Returns:
            从图片中提取/生成的文本。处理失败时应返回空字符串，
            由调用方决定是否回退到占位符。
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        """返回后端名称，用于缓存键和日志。"""
        raise NotImplementedError

    @property
    def model_name(self) -> str | None:
        """返回模型名称，用于缓存键。默认无。"""
        return None
