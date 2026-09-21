"""纯文本提取器（参考 Onyx extract_file_text.py）

支持编码自动检测、ONYX_METADATA 元数据提取、BOM 处理。
覆盖扩展名: .txt .json .xml .yml .yaml .sql .log .conf .csv .tsv
"""

from __future__ import annotations

import io
import json as json_mod
import os
import re
from typing import Any

from extractors.base import DocumentExtractor


def _detect_encoding(file_path: str) -> str:
    """使用 chardet 自动检测文件编码（参考 Onyx detect_encoding）。"""
    import chardet

    with open(file_path, "rb") as f:
        raw_data = f.read(50000)
    result = chardet.detect(raw_data)
    return result.get("encoding") or "utf-8"


def _extract_onyx_metadata(line: str) -> dict[str, Any] | None:
    """从文件第一行提取 ONYX_METADATA（参考 Onyx _extract_onyx_metadata）。"""
    html_comment_pattern = r"<!--\s*ONYX_METADATA=\{(.*?)\}\s*-->"
    hashtag_pattern = r"#ONYX_METADATA=\{(.*?)\}"

    html_match = re.search(html_comment_pattern, line)
    hashtag_match = re.search(hashtag_pattern, line)

    if html_match:
        json_str = html_match.group(1)
    elif hashtag_match:
        json_str = hashtag_match.group(1)
    else:
        return None

    try:
        return json_mod.loads("{" + json_str + "}")
    except json_mod.JSONDecodeError:
        return None


class TextExtractor(DocumentExtractor):
    """通用纯文本提取器，支持编码检测和元数据提取。"""

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        encoding = _detect_encoding(file_path)
        metadata: dict[str, Any] = {}

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        content_lines: list[str] = []
        for idx, line in enumerate(lines):
            # 处理 BOM（UTF-8 BOM 在 decode 时已被去除，但保险起见）
            if idx == 0 and line.startswith("\ufeff"):
                line = line[1:]

            # 第一行尝试提取 ONYX_METADATA
            if idx == 0:
                potential_meta = _extract_onyx_metadata(line)
                if potential_meta is not None:
                    metadata = potential_meta
                    continue

            content_lines.append(line)

        text = "".join(content_lines)
        return text, metadata, []


class JsonExtractor(DocumentExtractor):
    """JSON 提取器：格式化 JSON 为可读文本。"""

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        encoding = _detect_encoding(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            raw = f.read()

        metadata: dict[str, Any] = {}
        try:
            data = json_mod.loads(raw)
            # 尝试提取标题类字段
            for key in ("title", "name", "Title", "Name"):
                if isinstance(data, dict) and key in data:
                    metadata["Title"] = str(data[key])
                    break
            # 美化输出
            text = json_mod.dumps(data, ensure_ascii=False, indent=2)
        except json_mod.JSONDecodeError:
            text = raw

        return text, metadata, []


class XmlExtractor(DocumentExtractor):
    """XML 提取器：去除标签，保留文本内容。"""

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        encoding = _detect_encoding(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            raw = f.read()

        # 简单去除 XML 标签
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

        # 尝试提取 title
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.IGNORECASE)
        metadata: dict[str, Any] = {}
        if title_match:
            metadata["Title"] = title_match.group(1).strip()

        return text, metadata, []


class CsvExtractor(DocumentExtractor):
    """CSV/TSV 提取器：转为表格文本。"""

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        import csv

        encoding = _detect_encoding(file_path)
        delimiter = "\t" if file_path.lower().endswith(".tsv") else ","

        with open(file_path, "r", encoding=encoding, errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)

        if not rows:
            return "", {}, []

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)

        # 构建可读文本版本（类似表格）
        lines = [" | ".join(row) for row in rows]
        readable = "\n".join(lines)

        metadata: dict[str, Any] = {}
        return output.getvalue() + "\n\n" + readable, metadata, []


class LogExtractor(DocumentExtractor):
    """日志文件提取器：保留原始内容，提取时间戳作为元数据。"""

    TIMESTAMP_PATTERN = re.compile(
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})"
    )

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        encoding = _detect_encoding(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            text = f.read()

        # 提取时间戳范围
        timestamps = self.TIMESTAMP_PATTERN.findall(text)
        metadata: dict[str, Any] = {}
        if timestamps:
            metadata["LogTimeRange"] = f"{timestamps[0]} ~ {timestamps[-1]}"
            metadata["LogEntries"] = len(timestamps)

        return text, metadata, []
