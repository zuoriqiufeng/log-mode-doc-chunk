"""日志模式多格式解析器。

支持 JSON / YAML / CSV / TSV / Excel。
"""

from __future__ import annotations

import abc
import csv
import json
import os
from typing import Any

from log_patterns.models import LogPattern


# 字段别名映射：标准化 -> 可能的输入名
_FIELD_ALIASES: dict[str, list[str]] = {
    "pattern_id": ["pattern_id", "patternId", "pattern-id", "id", "pattern"],
    "log_fingerprint": [
        "log_fingerprint",
        "logFingerprint",
        "fingerprint",
        "log_fingerprints",
        "fingerprints",
    ],
    "component": ["component", "module", "service", "process"],
    "severity": ["severity", "level"],
    "symptom": ["symptom", "symptoms"],
    "root_cause": ["root_cause", "rootCause", "cause", "root_causes"],
    "remediation": ["remediation", "remediations", "fix", "fixes", "solution"],
    "error_codes": ["error_codes", "errorCodes", "error_code", "codes"],
    "db_types": ["db_types", "dbTypes", "db_type", "databases"],
    "false_positive": ["false_positive", "falsePositive", "false_positives"],
    "source_note": ["source_note", "sourceNote", "source", "note"],
    "updated_at": ["updated_at", "updatedAt", "updated", "update_time"],
    "metadata": ["metadata", "meta"],
}


# 需要按分隔符拆分为列表的字段
_LIST_FIELDS = {
    "log_fingerprint",
    "remediation",
    "error_codes",
    "db_types",
}


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """将原始记录字段名统一为标准 snake_case 字段。"""
    # 建立 输入名 -> 标准名 映射
    alias_to_standard: dict[str, str] = {}
    for standard, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            alias_to_standard[alias.lower()] = standard

    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        standard_key = alias_to_standard.get(key.lower().strip())
        if not standard_key:
            standard_key = key.strip()
        normalized[standard_key] = value

    # 将逗号/分号/竖线分隔的字符串转换为列表
    for field in _LIST_FIELDS:
        if field in normalized and isinstance(normalized[field], str):
            normalized[field] = [
                p.strip()
                for p in normalized[field].replace("|", ";").split(";")
                if p.strip()
            ]

    return normalized


def _record_to_pattern(record: dict[str, Any]) -> LogPattern:
    """将标准化记录转换为 LogPattern。"""
    norm = _normalize_record(record)
    return LogPattern(
        pattern_id=str(norm.get("pattern_id", "")),
        log_fingerprint=norm.get("log_fingerprint") or [],
        component=str(norm.get("component", "")),
        severity=str(norm.get("severity", "")),
        symptom=str(norm.get("symptom", "")),
        root_cause=str(norm.get("root_cause", "")),
        remediation=norm.get("remediation") or [],
        error_codes=norm.get("error_codes") or [],
        db_types=norm.get("db_types") or [],
        false_positive=str(norm.get("false_positive", "")),
        source_note=str(norm.get("source_note", "")),
        updated_at=str(norm.get("updated_at", "")),
        metadata=norm.get("metadata") or {},
    )


class BaseLogPatternParser(abc.ABC):
    """日志模式解析器抽象基类。"""

    @abc.abstractmethod
    def parse(self, file_path: str) -> list[LogPattern]:
        """解析文件，返回 LogPattern 列表。"""
        ...


class JsonLogPatternParser(BaseLogPatternParser):
    def parse(self, file_path: str) -> list[LogPattern]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            # 单个对象或顶层是 {"patterns": [...]}
            if "patterns" in data and isinstance(data["patterns"], list):
                data = data["patterns"]
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValueError(f"JSON 文件顶层应为对象或数组: {file_path}")

        return [_record_to_pattern(record) for record in data]


class YamlLogPatternParser(BaseLogPatternParser):
    def parse(self, file_path: str) -> list[LogPattern]:
        try:
            import yaml
        except ImportError as e:
            raise RuntimeError("解析 YAML 需要 pyyaml: pip install pyyaml") from e

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, dict):
            if "patterns" in data and isinstance(data["patterns"], list):
                data = data["patterns"]
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValueError(f"YAML 文件顶层应为对象或数组: {file_path}")

        return [_record_to_pattern(record) for record in data]


class CsvLogPatternParser(BaseLogPatternParser):
    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def parse(self, file_path: str) -> list[LogPattern]:
        patterns: list[LogPattern] = []
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            for row in reader:
                if not any(v for v in row.values() if v):
                    continue
                patterns.append(_record_to_pattern(row))
        return patterns


class ExcelLogPatternParser(BaseLogPatternParser):
    def __init__(self, sheet_name: str | None = None):
        self.sheet_name = sheet_name

    def parse(self, file_path: str) -> list[LogPattern]:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".xlsx":
            try:
                from openpyxl import load_workbook
            except ImportError as e:
                raise RuntimeError(
                    "解析 .xlsx 需要 openpyxl: pip install openpyxl"
                ) from e

            wb = load_workbook(file_path, data_only=True)
            ws = wb[self.sheet_name] if self.sheet_name else wb.active
            headers = [str(c.value or "").strip() for c in next(ws.iter_rows())]
            rows = []
            for row in ws.iter_rows(min_row=2):
                row_dict = {
                    headers[i]: str(cell.value) if cell.value is not None else ""
                    for i, cell in enumerate(row)
                    if i < len(headers)
                }
                if any(row_dict.values()):
                    rows.append(row_dict)
            return [_record_to_pattern(r) for r in rows]

        if ext == ".xls":
            try:
                import xlrd
            except ImportError as e:
                raise RuntimeError("解析 .xls 需要 xlrd: pip install xlrd") from e

            book = xlrd.open_workbook(file_path)
            sheet = book.sheet_by_name(self.sheet_name) if self.sheet_name else book.sheet_by_index(0)
            headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
            rows = []
            for row_idx in range(1, sheet.nrows):
                row_dict = {
                    headers[col]: str(sheet.cell_value(row_idx, col))
                    for col in range(sheet.ncols)
                }
                if any(row_dict.values()):
                    rows.append(row_dict)
            return [_record_to_pattern(r) for r in rows]

        raise ValueError(f"不支持的 Excel 格式: {ext}")


def get_parser(file_path: str) -> BaseLogPatternParser:
    """根据文件扩展名返回对应解析器。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".json":
        return JsonLogPatternParser()
    if ext in (".yaml", ".yml"):
        return YamlLogPatternParser()
    if ext == ".csv":
        return CsvLogPatternParser(delimiter=",")
    if ext == ".tsv":
        return CsvLogPatternParser(delimiter="\t")
    if ext in (".xlsx", ".xls"):
        return ExcelLogPatternParser()
    raise ValueError(f"不支持的日志模式文件格式: {ext}")
