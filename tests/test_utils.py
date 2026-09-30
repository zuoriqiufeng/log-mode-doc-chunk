"""utils 工具测试：表格检测的触发、解析与消费行返回。"""

from __future__ import annotations

from utils import detect_and_parse_table


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
