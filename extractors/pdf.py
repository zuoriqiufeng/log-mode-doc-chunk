"""PDF 提取器（参考 Onyx read_pdf_file）"""

from __future__ import annotations

import io
from typing import Any

from extractors.base import DocumentExtractor


class PdfExtractor(DocumentExtractor):
    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        from pypdf import PdfReader

        metadata: dict[str, Any] = {}
        images: list[tuple[bytes, str]] = []

        with open(file_path, "rb") as f:
            reader = PdfReader(f)

            if reader.is_encrypted:
                try:
                    if reader.decrypt("") == 0:
                        return "", metadata, []
                except Exception:
                    return "", metadata, []

            # 元数据
            if reader.metadata is not None:
                for key, value in reader.metadata.items():
                    clean_key = key.lstrip("/")
                    if isinstance(value, str) and value.strip():
                        metadata[clean_key] = value
                    elif isinstance(value, list) and all(
                        isinstance(item, str) for item in value
                    ):
                        metadata[clean_key] = ", ".join(value)

            # 文本
            text = "\n\n".join(
                page.extract_text() or "" for page in reader.pages
            )

            # 图片
            for page_num, page in enumerate(reader.pages):
                for img_obj in page.images:
                    try:
                        from PIL import Image
                        image = Image.open(io.BytesIO(img_obj.data))
                        buf = io.BytesIO()
                        image.save(buf, format=image.format or "PNG")
                        img_bytes = buf.getvalue()
                        fmt = (image.format or "png").lower()
                        name = f"page_{page_num + 1}_image_{img_obj.name}.{fmt}"
                        images.append((img_bytes, name))
                    except Exception:
                        pass

        return text, metadata, images
