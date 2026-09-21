"""提取器测试：扩展名分发 + 各格式在 word/sample.* 上的实际提取结果。"""

from __future__ import annotations

import os

import pytest

from extractors import EXTRACTOR_MAP, get_extractor
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


class TestExtractorMap:
    @pytest.mark.parametrize(
        ("ext", "expected"),
        [
            (".pdf", PdfExtractor),
            (".docx", DocxExtractor),
            (".md", MarkdownExtractor),
            (".html", HtmlExtractor),
            (".htm", HtmlExtractor),
            (".txt", TextExtractor),
            (".json", JsonExtractor),
            (".xml", XmlExtractor),
            (".log", LogExtractor),
            (".csv", CsvExtractor),
            (".tsv", CsvExtractor),
            (".xlsx", ExcelExtractor),
            (".png", ImageExtractor),
        ],
    )
    def test_dispatch_by_extension(self, ext, expected):
        assert EXTRACTOR_MAP[ext] is expected
        assert isinstance(get_extractor(f"any/file{ext}"), expected)

    def test_extension_matching_is_case_insensitive(self, tmp_path):
        path = tmp_path / "README.MD"
        path.write_text("# hi", encoding="utf-8")
        assert isinstance(get_extractor(str(path)), MarkdownExtractor)

    def test_unknown_extension_with_text_content_falls_back_to_text(self, tmp_path):
        path = tmp_path / "notes.unknownext"
        path.write_text("plain ascii content", encoding="utf-8")
        assert isinstance(get_extractor(str(path)), TextExtractor)

    def test_unknown_extension_missing_file_still_returns_text(self, tmp_path):
        # 文件不存在时探测失败，但仍应回退到 TextExtractor 而不是抛错
        assert isinstance(
            get_extractor(str(tmp_path / "nope.weird")), TextExtractor
        )


class TestTextExtractor:
    def test_extract_onyx_metadata_from_first_line(self, tmp_path):
        path = tmp_path / "meta.txt"
        path.write_text(
            '#ONYX_METADATA={"Title": "报表", "Author": "ops"}\n正文第一行\n正文第二行\n',
            encoding="utf-8",
        )
        text, metadata, images = TextExtractor().extract(str(path))

        assert metadata == {"Title": "报表", "Author": "ops"}
        assert "ONYX_METADATA" not in text
        assert text == "正文第一行\n正文第二行\n"
        assert images == []

    def test_extract_onyx_metadata_html_comment_form(self, tmp_path):
        path = tmp_path / "meta2.txt"
        path.write_text('<!-- ONYX_METADATA={"Title": "X"} -->\nbody\n', encoding="utf-8")
        text, metadata, _ = TextExtractor().extract(str(path))
        assert metadata == {"Title": "X"}
        assert text == "body\n"

    def test_metadata_only_on_first_line(self, tmp_path):
        path = tmp_path / "meta3.txt"
        path.write_text('#ONYX_METADATA={"Title": "A"}\n#ONYX_METADATA={"Title": "B"}\n', encoding="utf-8")
        text, metadata, _ = TextExtractor().extract(str(path))
        assert metadata == {"Title": "A"}
        assert "#ONYX_METADATA" in text


class TestSampleExtraction:
    """对 word/sample.* 做端到端提取，锁定各格式的真实可用性。"""

    @pytest.mark.parametrize(
        ("name", "expected_cls", "expected_meta_key"),
        [
            ("sample.md", MarkdownExtractor, "Title"),
            ("sample.html", HtmlExtractor, "Title"),
            ("sample.json", JsonExtractor, "Title"),
            ("sample.xml", XmlExtractor, "Title"),
            ("sample.csv", CsvExtractor, None),
            ("sample.log", LogExtractor, "LogEntries"),
            ("sample.pdf", PdfExtractor, None),
            ("sample.docx", DocxExtractor, None),
        ],
    )
    def test_extract_returns_text_and_metadata(self, sample_file, name, expected_cls, expected_meta_key):
        path = sample_file(name)
        extractor = get_extractor(path)

        assert isinstance(extractor, expected_cls)
        text, metadata, images = extractor.extract(path)

        assert isinstance(text, str) and text.strip(), f"{name} 未提取到文本"
        assert isinstance(metadata, dict)
        assert isinstance(images, list)
        if expected_meta_key:
            assert expected_meta_key in metadata, f"{name} 缺少元数据 {expected_meta_key}"

    def test_csv_rows_preserved(self, sample_file):
        text, _, _ = CsvExtractor().extract(sample_file("sample.csv"))
        assert "Alice Johnson" in text
        assert "Eve Davis" in text

    def test_json_title_becomes_metadata(self, sample_file):
        text, metadata, _ = JsonExtractor().extract(sample_file("sample.json"))
        assert metadata["Title"] == "API Configuration"
        assert "api-config" in text

    def test_log_timestamp_range_captured(self, sample_file):
        text, metadata, _ = LogExtractor().extract(sample_file("sample.log"))
        assert metadata["LogEntries"] == 10
        assert metadata["LogTimeRange"].startswith("2025-01-15T08:23:01")
        assert "ERROR [auth]" in text

    def test_xml_tags_stripped(self, sample_file):
        text, metadata, _ = XmlExtractor().extract(sample_file("sample.xml"))
        assert metadata["Title"] == "System Configuration"
        assert "<title>" not in text
        assert "System Configuration" in text

    def test_markdown_frontmatter_becomes_metadata_and_is_stripped(self, sample_file):
        text, metadata, _ = MarkdownExtractor().extract(sample_file("sample.md"))
        assert metadata["Title"] == "API Documentation Guide"
        # frontmatter 已从正文移除
        assert "---" not in text.split("\n")[0]
        assert not text.lstrip().startswith("title:")

    def test_markdown_headings_use_level_markers(self, sample_file):
        """标题被转换为【H1】/【H2】标记，便于分块器识别层级。"""
        text, _, _ = MarkdownExtractor().extract(sample_file("sample.md"))
        assert "【H1】API Documentation Guide" in text
        assert "【H2】Authentication" in text
        assert "# API Documentation Guide" not in text
