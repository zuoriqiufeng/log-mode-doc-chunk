"""文档预富化模块 — 检测数字/符号串并追加语义锚点。

策略：在切块之前，扫描原始文本中的错误码、版本号、数据库简称等符号串，
生成结构化的语义标注块，作为独立的文本段落参与后续分块和 BGE embedding。
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Annotation(NamedTuple):
    """检测到的符号串及其语义标注。"""
    raw: str           # 原始匹配文本
    enriched: str      # 富化后的表述
    type: str          # 数据类型标签
    position: int      # 在原文中的字符位置
    version: str = "1.0"  # 标注版本，供审计追踪


# ------------------------------------------------------------------ #
# 辅助函数
# ------------------------------------------------------------------ #

def _build_error_code(m: re.Match) -> str:
    """从错误码 regex 的 3 种匹配模式中构建标注文本。

    模式 1: IAERR_LOG_SEQ | -4002 → g(1)=IAERR, g(2)=-4002
    模式 2: -4002 | 描述文本 → g(3)=-4002, g(4)=描述
    模式 3: 错误码: -4002 → g(5)=-4002
    """
    g = m.groups()
    code = ""
    name = ""
    if g[0] is not None and g[1] is not None:
        name = g[0]
        code = g[1]
    elif g[2] is not None and g[3] is not None:
        code = g[2]
        name = g[3]
    elif len(g) > 4 and g[4] is not None:
        code = g[4]
    if not code:
        return ""
    code = code.lstrip("-")
    result = f"错误码 -{code}"
    if name and name.strip():
        result += f" ({name.strip()})"
    return result


# ------------------------------------------------------------------ #
# 检测器注册表
# ------------------------------------------------------------------ #

DETECTOR_REGISTRY: list[dict] = [
    # 1. 错误码 (IAERR_LOG_SEQ | 4002 或 4002 | 描述 或 错误码: 4002)
    {
        "name": "error_code",
        "pattern": re.compile(
            r'(IAERR_[A-Z_]+)\s*\|\s*(-?\d{4,})'
            r'|(-?\d{4,})\s*\|\s*(.{1,80})'
            r'|错误码[：:]\s*(-?\d{4,})',
            re.IGNORECASE,
        ),
        "enrich": lambda m: _build_error_code(m),
    },
    # 2. 版本号 (Oracle 19c, i2Stream 9.1.4, MySQL 8.0, DB2 11.5)
    {
        "name": "version",
        "pattern": re.compile(
            r'(Oracle|MySQL|DB2|DM|OB|TDSQL|GaussDB|PostgreSQL|OceanBase|i2Stream)'
            r'\s+(\d+[gc]|\d+\.\d+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
        "enrich": lambda m: f"{m.group(1)} {m.group(2)}",
    },
    # 3. 数据库简称（前后有中文/冒号/行首行尾，避免误匹配英文单词）
    {
        "name": "database",
        "pattern": re.compile(
            r'(?:^|[:：\s])'
            r'(Oracle|MySQL|DB2|DM|OB|达梦|TDSQL|GaussDB|PostgreSQL|OceanBase|Kingbase|人大金仓|南大通用)'
            r'(?=[\s，,。:；;]|$)',
        ),
        "enrich": lambda m: m.group(1),
    },
    # 4. 端口号（带上下文关键词 port/端口/监听）
    {
        "name": "port",
        "pattern": re.compile(
            r'(?:port|端口|端口号|监听)[：:=\s]*(\d{4,5})',
            re.IGNORECASE,
        ),
        "enrich": lambda m: m.group(1),
    },
    # 5. 配置参数 (DB2CODEPAGE=1208, type.conversion.xxx)
    {
        "name": "config_param",
        "pattern": re.compile(
            r'\b([A-Z][A-Z0-9_]{3,}(?:\.[A-Z][A-Z0-9_]+)*)\s*[=：:]\s*([\w./_-]+)',
        ),
        "enrich": lambda m: f"{m.group(1)}={m.group(2)}",
    },
    # 6. UUID
    {
        "name": "uuid",
        "pattern": re.compile(
            r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}',
            re.IGNORECASE,
        ),
        "enrich": lambda m: m.group(0),
    },
    # 7. IP 地址（含上下文 host/ip/addr/地址/connect）
    {
        "name": "ip",
        "pattern": re.compile(
            r'(?:host|ip|addr|地址|connect|连接|source)[：:=\s]*'
            r'((?:\d{1,3}\.){3}\d{1,3})',
            re.IGNORECASE,
        ),
        "enrich": lambda m: m.group(1),
    },
    # 8. 文件路径（绝对路径，含上下文 路径/目录/log_dir/dir）
    {
        "name": "filepath",
        "pattern": re.compile(
            r'(?:路径|目录|log_dir|base_dir|dir|stored at)[：:=\s]*'
            r'(/\w+(?:/[\w._-]+)+)',
            re.IGNORECASE,
        ),
        "enrich": lambda m: m.group(1),
    },
]

# ------------------------------------------------------------------ #
# 公共 API
# ------------------------------------------------------------------ #


def detect_annotations(text: str) -> list[Annotation]:
    """扫描文本，返回检测到的所有语义标注。

    去重策略：相同 type + 相同 enriched → 只保留一个。
    """
    seen: set[tuple[str, str]] = set()
    results: list[Annotation] = []

    for detector in DETECTOR_REGISTRY:
        for match in detector["pattern"].finditer(text):
            enriched = detector["enrich"](match).strip()
            if not enriched:
                continue
            key = (detector["name"], enriched.lower())
            if key not in seen:
                seen.add(key)
                results.append(Annotation(
                    raw=match.group(0),
                    enriched=enriched,
                    type=detector["name"],
                    position=match.start(),
                ))

    results.sort(key=lambda a: a.position)
    return results


def enrich_document_text(text: str, annotations: list[Annotation] | None = None) -> str:
    """在原文档末尾追加结构化标注块，供 BGE 编码时提供语义锚点。

    Args:
        text: 原始文档文本。如果为空字符串，只返回标注块（用于独立 Section）。
        annotations: 预检测的注解列表。如果为 None，自动检测。

    标注格式:
        ---
        关联错误码: -4002 (IAERR_LOG_SEQ), -4000
        涉及版本: Oracle 19c, i2Stream 9.1.4
        数据库: Oracle
        端口: 1521
        配置参数: DB2CODEPAGE=1208
        规则UUID: 9DED5F94-2634-4150-8F81-B4E85E098578
        IP地址: 192.168.30.102
        文件路径: /hdd/demo/logs/log
    """
    if annotations is None:
        if not text:
            return ""
        annotations = detect_annotations(text)

    if not annotations:
        return text

    types_found: dict[str, list[str]] = {}
    for a in annotations:
        types_found.setdefault(a.type, []).append(a.enriched)

    type_order = [
        "error_code", "version", "database", "port",
        "config_param", "uuid", "ip", "filepath",
    ]
    type_labels = {
        "error_code":    "关联错误码",
        "version":       "涉及版本",
        "database":      "数据库",
        "port":          "端口",
        "config_param":  "配置参数",
        "uuid":          "规则UUID",
        "ip":            "IP地址",
        "filepath":      "文件路径",
    }

    parts: list[str] = []
    for t in type_order:
        if t in types_found:
            label = type_labels.get(t, t)
            parts.append(f"{label}: {', '.join(types_found[t])}")

    if not parts:
        return text

    annotation_block = "\n\n---\n" + "\n".join(parts)
    if text:
        return text + annotation_block
    return annotation_block.lstrip("\n")
