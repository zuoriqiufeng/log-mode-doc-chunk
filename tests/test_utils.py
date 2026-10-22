"""utils 工具测试：表格检测与退化哨兵。"""

from __future__ import annotations

import pytest

from models import DocAwareChunk, Document
from utils import check_chunk_limits, detect_and_parse_table


class TestDetectAndParseTable:
    def test_关键词触发表格并返回消费行(self):
        lines = [
            "Connector Comparison Table",
            "The following table compares different connector types:",
            "Connector", "Type", "Real-time", "Permissions",
            "Confluence", "Cloud", "Yes", "OAuth + API Token",
            "Google Drive", "Cloud", "Yes", "OAuth 2.0 Service Account",
            "SharePoint", "Cloud", "Yes", "SAML",
        ]
        result = detect_and_parse_table("\n".join(lines))
        assert result is not None
        heading, csv_text, consumed = result

        assert heading == "Connector Comparison Table"
        assert "Connector,Type,Real-time,Permissions" in csv_text
        # 消费行 = 写入 CSV 的单元格原文；长 intro 行不在其中
        assert "Google Drive" in consumed
        assert "OAuth 2.0 Service Account" in consumed
        assert "The following table compares different connector types:" not in consumed
        # 消费行都能在原文中按行找到——这是调用方按行去重的前提
        raw_lines = {line.strip() for line in lines}
        assert set(consumed) <= raw_lines

    def test_表头词触发表格(self):
        lines = ["Connector", "Type", "Real-time", "Permissions"] + [
            f"value{i}" for i in range(9)
        ]
        result = detect_and_parse_table("\n".join(lines))
        assert result is not None
        heading, _, consumed = result

        assert heading == "Connector"
        assert len(consumed) == 12
        assert "value8" in consumed

    def test_不足8行不判为表格(self):
        assert detect_and_parse_table("表格\na\nb\nc\nd\ne\nf\ng") is None

    def test_无触发词返回None(self):
        text = "普通第一行\n普通第二行内容稍微长一些不是单元格\n第三行内容"
        assert detect_and_parse_table(text) is None


def _make_chunk(
    content: str,
    chunk_id: int = 0,
    chunk_level: str = "standard",
    is_large_chunk: bool = False,
    mini_chunk_texts: list[str] | None = None,
) -> DocAwareChunk:
    document = Document(id="doc", semantic_identifier="doc", sections=[])
    return DocAwareChunk(
        source_document=document,
        chunk_id=chunk_id,
        content=content,
        blurb="",
        chunk_level=chunk_level,
        is_large_chunk=is_large_chunk,
        mini_chunk_texts=mini_chunk_texts,
    )


class TestCheckChunkLimits:
    def test_合规集合无发现(self):
        chunks = [_make_chunk("a" * 100, mini_chunk_texts=["b" * 100])]
        assert check_chunk_limits(chunks, 2048, 600) == ([], [])

    def test_超长标准块与超限mini被列出且大块被排除(self):
        big = _make_chunk("x" * 3000, chunk_id=1)
        big_large = _make_chunk(
            "y" * 9000, chunk_id=2, chunk_level="large", is_large_chunk=True
        )
        with_over = _make_chunk("ok", chunk_id=3, mini_chunk_texts=["m" * 700, "s"])
        oversize, oversize_minis = check_chunk_limits(
            [big, big_large, with_over], 2048, 600
        )

        assert oversize == [big], "large 块天然超长，不在超长清单中"
        assert oversize_minis == [(with_over, 0, 700)]

    def test_strict模式违约时抛RuntimeError(self):
        chunks = [_make_chunk("x" * 3000)]
        with pytest.raises(RuntimeError, match="退化"):
            check_chunk_limits(chunks, 2048, 600, strict=True)
