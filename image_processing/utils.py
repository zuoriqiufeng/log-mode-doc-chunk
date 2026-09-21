"""图片处理工具函数。"""

from __future__ import annotations

import base64
import io


def encode_image_to_base64(image_bytes: bytes) -> str:
    """将图片二进制数据编码为 base64 字符串。"""
    return base64.b64encode(image_bytes).decode("utf-8")


def is_too_small(image_bytes: bytes, min_width: int, min_height: int) -> bool:
    """判断图片是否过小，跳过无意义的处理。"""
    if min_width <= 0 and min_height <= 0:
        return False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
            if width < min_width or height < min_height:
                return True
    except Exception:
        # 无法解析时保守跳过处理
        return True
    return False


def build_image_chunk_text(filename: str, processed_text: str) -> str:
    """构造图片 Section / chunk 的文本内容。

    若处理后有文本，则返回包含原文件名和处理结果的文本；
    否则返回原有占位符，保持向后兼容。
    """
    if processed_text:
        return f"[图片: {filename}]\n{processed_text}"
    return f"[嵌入图片: {filename}]"
