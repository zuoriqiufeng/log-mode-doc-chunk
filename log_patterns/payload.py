"""日志模式 Qdrant payload 构建。"""

from __future__ import annotations

from typing import Any

from log_patterns.models import LogPattern


def build_pattern_payload(pattern: LogPattern, chunk_type: str) -> dict[str, Any]:
    """为 standard 或 mini chunk 构建 payload。

    Args:
        pattern: 日志模式对象
        chunk_type: "standard" 或 "mini"
    """
    return {
        "is_log_pattern": True,
        "pattern_id": pattern.pattern_id,
        "log_fingerprint": pattern.log_fingerprint,
        "component": pattern.component,
        "severity": pattern.severity,
        "error_codes": pattern.error_codes,
        "db_types": pattern.db_types,
        "keywords": pattern.log_fingerprint,
        "source_note": pattern.source_note,
        "updated_at": pattern.updated_at,
        "chunk_type": chunk_type,
    }
