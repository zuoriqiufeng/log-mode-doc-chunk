"""提取器测试：扩展名分发 + 各格式在 word/sample.* 上的实际提取结果。"""

from __future__ import annotations

import os
import re

import pytest

from chunking.text import chunk_text_sections
from extractors import EXTRACTOR_MAP, get_extractor
from extractors.docx import DocxExtractor
from extractors.excel import ExcelExtractor
from extractors.html import HtmlExtractor
from extractors.image import ImageExtractor
from extractors.markdown import MarkdownExtractor
from extractors.pdf import PdfExtractor, _reflow_page_text
from extractors.text import (
    CsvExtractor,
    JsonExtractor,
    LogExtractor,
    TextExtractor,
    XmlExtractor,
)
from models import Document, Section, SectionType
from pipeline import process_document


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


# ---------------------------------------------------------------------------
# PDF 折行重排（_reflow_page_text）与图片占位符
# ---------------------------------------------------------------------------

def _make_wrapped_line_pdf(path, sentences: int = 40, wrap_width: int = 60) -> None:
    """生成按视觉宽度折行的多页 PDF（模拟 pypdf 常见的折行输出）。"""
    import textwrap

    from reportlab.pdfgen import canvas

    body = " ".join(
        f"Sentence {i} describes the database deployment and verification procedure."
        for i in range(sentences)
    )
    c = canvas.Canvas(str(path))
    y = 800
    for line in textwrap.wrap(body, wrap_width):
        c.drawString(50, y, line)
        y -= 14
        if y < 60:
            c.showPage()
            y = 800
    c.save()


def _make_pdf_with_image(path) -> None:
    """生成两页 PDF：第 1 页正文 + 一张嵌入图片，第 2 页仅正文。"""
    from PIL import Image as PILImage
    from reportlab.pdfgen import canvas

    img_path = path.parent / "embed.png"
    PILImage.new("RGB", (60, 40), (200, 80, 80)).save(img_path)
    c = canvas.Canvas(str(path))
    c.drawString(50, 800, "Page one has a figure below this line.")
    c.drawImage(str(img_path), 50, 600, width=120, height=80)
    c.showPage()
    c.drawString(50, 800, "Page two contains plain text only.")
    c.save()


class TestPdfReflow:
    def test_英文折行按空格拼回并在句末停止(self):
        text = (
            "The deployment pipeline requires the database\n"
            "administrator to configure the parameter.\n"
            "Next sentence starts here."
        )
        out = _reflow_page_text(text)
        assert out == (
            "The deployment pipeline requires the database administrator"
            " to configure the parameter.\n\n"
            "Next sentence starts here."
        )

    def test_中文折行无空格直连(self):
        text = "部署前需要配置数据库编码参数并确认监听端口\n可达后再启动同步服务，否则会出现乱码问题。"
        out = _reflow_page_text(text)
        assert out == "部署前需要配置数据库编码参数并确认监听端口可达后再启动同步服务，否则会出现乱码问题。"

    def test_英文断词去连字符(self):
        text = "The process requires careful configu-\nration before startup."
        out = _reflow_page_text(text)
        assert out == "The process requires careful configuration before startup."

    def test_列表项不向外续行也不被并入(self):
        text = (
            "Core features include the following items\n"
            "- Agentic RAG with hybrid indexing\n"
            "- Deep Research for reports"
        )
        out = _reflow_page_text(text)
        assert out.split("\n\n") == [
            "Core features include the following items",
            "- Agentic RAG with hybrid indexing",
            "- Deep Research for reports",
        ]

    def test_空行分段(self):
        text = "第一段的第一行结束的时候没有句末标点符号\n第二行接上之后才有句号。\n\n第二段完整。"
        out = _reflow_page_text(text)
        assert out == "第一段的第一行结束的时候没有句末标点符号第二行接上之后才有句号。\n\n第二段完整。"

    def test_表格单元格不被合并且检测仍可用(self):
        lines = [
            "Connector Comparison Table",
            "The following table compares different connector types:",
            "Connector", "Type", "Real-time", "Permissions",
            "Confluence", "Cloud", "Yes", "OAuth + API Token",
            "Google Drive", "Cloud", "Yes", "OAuth 2.0 Service Account",
            "SharePoint", "Cloud", "Yes", "SAML",
        ]
        out = _reflow_page_text("\n".join(lines))
        # 表格保护区保持一行一格
        assert "Connector\nType\nReal-time\nPermissions" in out

        from utils import detect_and_parse_table
        result = detect_and_parse_table(out)
        assert result is not None
        heading, csv_text, _consumed = result
        assert "Comparison Table" in heading
        assert len(csv_text.strip().splitlines()) >= 3

    def test_题注行不被并入上一段也不吸收下一行(self):
        text = (
            "前一段内容很长这里假设它没有句末标点仍然在继续延伸\n"
            "Connector Comparison Table\n"
            "The following table compares:"
        )
        out = _reflow_page_text(text)
        assert out.split("\n\n") == [
            "前一段内容很长这里假设它没有句末标点仍然在继续延伸",
            "Connector Comparison Table",
            "The following table compares:",
        ]

    def test_空文本与超长单行原样返回(self):
        assert _reflow_page_text("") == ""
        assert _reflow_page_text("   \n  \n") == ""
        assert _reflow_page_text("单个完整句子。") == "单个完整句子。"
        long_line = "很" * 3000
        assert _reflow_page_text(long_line) == long_line


class TestPdfReflowSeam:
    def test_重排后文本块接缝不再落在句子中间(self, tmp_path):
        """修复前：接缝落在视觉折行处、切进句子中间，本用例的断言必挂。"""
        pdf_path = tmp_path / "wrapped.pdf"
        _make_wrapped_line_pdf(pdf_path)
        text, _, _ = PdfExtractor().extract(str(pdf_path))

        document = Document(
            id="wrapped",
            semantic_identifier="wrapped",
            sections=[Section(type=SectionType.TEXT, text=text)],
            title="wrapped",
        )
        chunks = chunk_text_sections(document.sections, document, chunk_token_limit=512)

        assert len(chunks) > 1, "合成 PDF 应产生多个文本块"
        for c in chunks[:-1]:
            tail = c.content.rstrip()[-1]
            assert tail in "。．.!?！？；;：:…", (
                f"块 {c.chunk_id} 接缝切在句中: ...{c.content[-30:]!r}"
            )


class TestPdfImagePlaceholder:
    def test_占位符独立成段且与images序号对齐(self, tmp_path):
        pdf_path = tmp_path / "with_image.pdf"
        _make_pdf_with_image(pdf_path)
        text, _, images = PdfExtractor().extract(str(pdf_path))

        assert len(images) == 1
        found = re.findall(r"【PIC:(\d+)】", text)
        assert found == [str(i) for i in range(len(images))]
        assert "【PIC:0】" in text.split("\n\n"), "占位符应独立成段"

    def test_图片经process_document产出image_chunk(self, tmp_path):
        pdf_path = tmp_path / "with_image.pdf"
        _make_pdf_with_image(pdf_path)
        out_dir = tmp_path / "out"

        _, chunks, _ = process_document(
            str(pdf_path),
            str(out_dir),
            enable_embedding=False,
            enable_vector_store=False,
            enable_contextual_rag=False,
            enable_large_chunks=False,
            enable_image_processing=False,
        )

        image_chunks = [c for c in chunks if c.section_type == SectionType.IMAGE]
        assert image_chunks, "PDF 图片应产出 image chunk"
        assert image_chunks[0].image_file_id
        assert image_chunks[0].content.startswith("[嵌入图片:")

    def test_document_sections不含重复图片段(self, tmp_path):
        """IMAGE Section 已含在 text_sections 里，Document.sections 不应再拼一遍。"""
        pdf_path = tmp_path / "with_image.pdf"
        _make_pdf_with_image(pdf_path)

        document, _, _ = process_document(
            str(pdf_path),
            str(tmp_path / "out"),
            enable_embedding=False,
            enable_vector_store=False,
            enable_contextual_rag=False,
            enable_large_chunks=False,
            enable_image_processing=False,
        )

        section_ids = [id(s) for s in document.sections]
        assert len(section_ids) == len(set(section_ids)), "Section 对象不应重复出现"
        image_count = sum(1 for s in document.sections if s.type == SectionType.IMAGE)
        assert image_count == 1
