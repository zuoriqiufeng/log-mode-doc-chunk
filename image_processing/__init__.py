"""图片处理包。

提供可插拔的本地/远程图片处理能力，提取或生成可用于文本嵌入的图片描述。
"""

from image_processing.base import BaseImageProcessor
from image_processing.cache import ImageCache
from image_processing.config import ImageProcessorConfig
from image_processing.factory import create_image_processor
from image_processing.local_processor import EasyOCRImageProcessor
from image_processing.remote_processor import OpenAIVisionProcessor
from image_processing.utils import build_image_chunk_text

__all__ = [
    "BaseImageProcessor",
    "ImageCache",
    "ImageProcessorConfig",
    "create_image_processor",
    "EasyOCRImageProcessor",
    "OpenAIVisionProcessor",
    "build_image_chunk_text",
]
