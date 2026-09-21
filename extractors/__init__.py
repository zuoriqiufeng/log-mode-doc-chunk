"""文档提取器包：根据文件扩展名分派对应的提取器。"""

from extractors.base import DocumentExtractor
from extractors.doc import DocExtractor
from extractors.docx import DocxExtractor
from extractors.excel import ExcelExtractor
from extractors.html import HtmlExtractor
from extractors.image import ImageExtractor
from extractors.markdown import MarkdownExtractor
from extractors.pdf import PdfExtractor
from extractors.text import (
    CsvExtractor,
    JsonExtractor,
    LogExtractor,
    TextExtractor,
    XmlExtractor,
)

EXTRACTOR_MAP: dict[str, type[DocumentExtractor]] = {
    # 文档
    ".pdf": PdfExtractor,
    ".docx": DocxExtractor,
    ".doc": DocExtractor,
    # 网页
    ".html": HtmlExtractor,
    ".htm": HtmlExtractor,
    # Markdown
    ".md": MarkdownExtractor,
    ".markdown": MarkdownExtractor,
    # 纯文本
    ".txt": TextExtractor,
    ".text": TextExtractor,
    ".conf": TextExtractor,
    ".cfg": TextExtractor,
    ".ini": TextExtractor,
    # JSON
    ".json": JsonExtractor,
    # XML
    ".xml": XmlExtractor,
    ".xsl": XmlExtractor,
    ".xsd": XmlExtractor,
    # YAML
    ".yml": TextExtractor,
    ".yaml": TextExtractor,
    # SQL
    ".sql": TextExtractor,
    # 日志
    ".log": LogExtractor,
    # Excel
    ".xlsx": ExcelExtractor,
    ".xls": ExcelExtractor,
    # CSV/TSV
    ".csv": CsvExtractor,
    ".tsv": CsvExtractor,
    # 图片
    ".png": ImageExtractor,
    ".jpg": ImageExtractor,
    ".jpeg": ImageExtractor,
    ".gif": ImageExtractor,
    ".bmp": ImageExtractor,
    ".tiff": ImageExtractor,
    ".tif": ImageExtractor,
}


def get_extractor(file_path: str) -> DocumentExtractor:
    """根据文件扩展名获取对应的提取器"""
    import os

    ext = os.path.splitext(file_path)[1].lower()
    extractor_cls = EXTRACTOR_MAP.get(ext)
    if not extractor_cls:
        # 未知扩展名尝试检测是否为纯文本
        try:
            import chardet

            with open(file_path, "rb") as f:
                raw = f.read(1024)
            text_chars = bytearray(
                {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}
            )
            if all(c in text_chars for c in raw):
                print(f"[INFO] 未知格式 '{ext}'，检测到纯文本，使用 TextExtractor")
                return TextExtractor()
        except Exception:
            pass
        print(f"[WARN] 未知格式 '{ext}'，尝试按纯文本处理")
        return TextExtractor()
    return extractor_cls()
