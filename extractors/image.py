"""图片文件提取器：提取图片元数据和描述文本。

支持格式: PNG, JPEG, GIF, BMP, TIFF
使用 PIL (Pillow) 提取图片格式、尺寸、模式、DPI 和 EXIF 信息。
"""

from __future__ import annotations

import io
import os
from typing import Any

from extractors.base import DocumentExtractor


class ImageExtractor(DocumentExtractor):
    """图片文件提取器。

    将图片元数据（格式、尺寸、模式等）和 EXIF 信息提取为文本，
    使图片文件也能被分块和向量化检索。
    """

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("Pillow 包未安装，请运行: pip install Pillow")

        filename = os.path.basename(file_path)
        metadata: dict[str, Any] = {}
        text_parts: list[str] = []

        try:
            img = Image.open(file_path)
            img.load()

            # 基本信息
            fmt = img.format or "UNKNOWN"
            width, height = img.size
            mode = img.mode

            metadata["format"] = fmt
            metadata["width"] = width
            metadata["height"] = height
            metadata["mode"] = mode

            text_parts.append(f"图片文件: {filename}")
            text_parts.append(f"格式: {fmt}")
            text_parts.append(f"尺寸: {width}x{height}")
            text_parts.append(f"颜色模式: {mode}")

            # DPI 信息
            if img.info.get("dpi"):
                dpi_x, dpi_y = img.info["dpi"]
                metadata["dpi"] = f"{dpi_x:.0f}x{dpi_y:.0f}"
                text_parts.append(f"DPI: {dpi_x:.0f}x{dpi_y:.0f}")

            # EXIF 数据
            exif_data = self._extract_exif(img, metadata)
            if exif_data:
                text_parts.append("EXIF 信息:")
                text_parts.extend(exif_data)

            # 文件大小
            file_size = os.path.getsize(file_path)
            size_str = self._format_file_size(file_size)
            metadata["file_size"] = file_size
            text_parts.append(f"文件大小: {size_str}")

            # 读取图片二进制数据（用于保存）
            img_bytes = self._read_image_bytes(file_path)

            img.close()

        except Exception as e:
            text_parts.append(f"[图片读取失败: {e}]")
            metadata["error"] = str(e)
            img_bytes = None

        text = "\n".join(text_parts)
        images: list[tuple[bytes, str]] = []
        if img_bytes:
            images.append((img_bytes, filename))

        return text, metadata, images

    def _extract_exif(
        self, img, metadata: dict[str, Any]
    ) -> list[str]:
        """提取 EXIF 信息，返回可读的文本行列表。"""
        exif_lines: list[str] = []
        try:
            raw_exif = img.getexif()
        except Exception:
            return exif_lines

        if not raw_exif:
            return exif_lines

        # 常用 EXIF 标签映射
        tag_names = {
            271: "相机制造商",
            272: "相机型号",
            306: "拍摄日期",
            36867: "原始拍摄时间",
            37386: "焦距",
            33434: "曝光时间",
            33437: "光圈值",
            37500: "备注",
        }

        for tag_id, value in raw_exif.items():
            tag_name = tag_names.get(tag_id, f"EXIF_{tag_id}")
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8", errors="ignore").strip("\x00")
                except Exception:
                    continue
            value_str = str(value).strip()
            if value_str and value_str != "\x00":
                exif_lines.append(f"  {tag_name}: {value_str}")
                metadata[f"exif_{tag_name}"] = value_str

        return exif_lines

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    @staticmethod
    def _read_image_bytes(file_path: str) -> bytes | None:
        """读取图片文件的二进制数据。"""
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except Exception:
            return None
