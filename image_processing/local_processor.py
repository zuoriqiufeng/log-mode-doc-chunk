"""本地图片处理器：使用 EasyOCR 提取图片中的文字。"""

from __future__ import annotations

import io
from typing import Any

from image_processing.base import BaseImageProcessor
from image_processing.config import ImageProcessorConfig
from image_processing.utils import is_too_small


class EasyOCRImageProcessor(BaseImageProcessor):
    """基于 EasyOCR 的本地图片文字识别处理器。"""

    def __init__(
        self,
        languages: list[str] | None = None,
        device: str | None = None,
    ) -> None:
        self.languages = languages or ImageProcessorConfig.OCR_LANGUAGES
        self.device = (device or ImageProcessorConfig.OCR_DEVICE).lower()
        self._reader: Any | None = None

    @property
    def backend_name(self) -> str:
        return "easyocr"

    @property
    def model_name(self) -> str | None:
        return "+".join(self.languages)

    def _get_reader(self) -> Any:
        """懒加载 EasyOCR reader，避免每次处理都重新初始化模型。"""
        if self._reader is None:
            try:
                import easyocr
            except ImportError as e:
                raise RuntimeError(
                    "EasyOCR 未安装，请运行: "
                    "pip install easyocr>=1.7.0"
                ) from e

            use_gpu = self.device in ("cuda", "gpu", "cuda:0")
            self._reader = easyocr.Reader(
                self.languages,
                gpu=use_gpu,
                verbose=False,
            )
        return self._reader

    def process(self, image_bytes: bytes, filename: str = "") -> str:
        """识别图片中的文字并返回。"""
        if is_too_small(
            image_bytes,
            ImageProcessorConfig.MIN_IMAGE_WIDTH,
            ImageProcessorConfig.MIN_IMAGE_HEIGHT,
        ):
            return ""

        try:
            from PIL import Image
        except ImportError as e:
            raise RuntimeError("Pillow 未安装") from e

        try:
            image = Image.open(io.BytesIO(image_bytes))
            image = image.convert("RGB")
            import numpy as np

            arr = np.array(image)
        except Exception as e:
            print(f"[WARN] 图片预处理失败 ({filename}): {e}")
            return ""

        try:
            reader = self._get_reader()
            texts = reader.readtext(arr, detail=0)
        except Exception as e:
            print(f"[WARN] EasyOCR 识别失败 ({filename}): {e}")
            return ""

        if not texts:
            return ""

        return "\n".join(text.strip() for text in texts if text.strip())
