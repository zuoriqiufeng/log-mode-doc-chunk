"""图片处理结果磁盘缓存。

    键基于图片内容哈希 + 后端 + 模型/语言，避免重复处理同一张图片。
"""

from __future__ import annotations

import hashlib
import json
import os

from image_processing.base import BaseImageProcessor
from image_processing.config import ImageProcessorConfig


class ImageCache:
    """图片处理结果缓存。"""

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or ImageProcessorConfig.CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def _make_key(
        self,
        image_bytes: bytes,
        processor: BaseImageProcessor,
    ) -> str:
        """生成缓存键。"""
        parts = [
            processor.backend_name,
            processor.model_name or "default",
            image_bytes,
        ]
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, image_bytes: bytes, processor: BaseImageProcessor) -> str | None:
        """获取缓存结果。返回 None 表示未命中。"""
        key = self._make_key(image_bytes, processor)
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("text", "")
        except Exception:
            return None

    def set(
        self,
        image_bytes: bytes,
        processor: BaseImageProcessor,
        text: str,
    ) -> None:
        """写入缓存结果（临时文件 + 原子替换，防并发写截断）。"""
        key = self._make_key(image_bytes, processor)
        path = self._cache_path(key)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"text": text}, f, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception as e:
            print(f"[WARN] 图片缓存写入失败: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass
