"""日志模式库数据模型。

参考: i2stream-bkn 项目《Qdrant 日志模式库设计》(doc/log-analysis/qdrant-log-pattern-library-design.md)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SEVERITY_LEVELS = {"critical", "high", "medium", "low"}


@dataclass
class LogPattern:
    """单条日志模式条目。

    字段与设计文档 3.1 节对齐。
    """

    pattern_id: str
    log_fingerprint: list[str]
    component: str
    severity: str = ""
    symptom: str = ""
    root_cause: str = ""
    remediation: list[str] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    db_types: list[str] = field(default_factory=list)
    false_positive: str = ""
    source_note: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint_text(self) -> str:
        """用于语义嵌入和关键词检索的指纹拼接文本。"""
        parts = [
            " ".join(self.log_fingerprint),
            self.component,
            " ".join(self.error_codes),
        ]
        return " ".join(p for p in parts if p).strip()

    def full_text(self) -> str:
        """标准 chunk 文本：包含完整模式信息。"""
        lines: list[str] = [
            f"Pattern ID: {self.pattern_id}",
            f"Component: {self.component}",
        ]
        if self.severity:
            lines.append(f"Severity: {self.severity}")
        if self.error_codes:
            lines.append(f"Error codes: {', '.join(self.error_codes)}")
        if self.db_types:
            lines.append(f"DB types: {', '.join(self.db_types)}")
        if self.log_fingerprint:
            lines.append(f"Log fingerprint: {', '.join(self.log_fingerprint)}")
        if self.symptom:
            lines.append(f"Symptom: {self.symptom}")
        if self.false_positive:
            lines.append(f"False positive: {self.false_positive}")
        if self.root_cause:
            lines.append(f"Root cause: {self.root_cause}")
        if self.remediation:
            lines.append("Remediation:")
            for step in self.remediation:
                lines.append(f"  - {step}")
        if self.source_note:
            lines.append(f"Source note: {self.source_note}")
        lines.append(f"Updated at: {self.updated_at}")
        return "\n".join(lines)

    def mini_texts(self) -> list[str]:
        """生成 2-4 个 mini chunk 文本。

        顺序：
        - mini-1: 日志特征指纹
        - mini-2: 根因
        - mini-3: 处置要点
        - mini-4: 症状 + 误判提示
        """
        minis: list[str] = []
        fp = self.fingerprint_text
        if fp:
            minis.append(fp)
        if self.root_cause:
            minis.append(self.root_cause)
        if self.remediation:
            minis.append(" ".join(self.remediation))
        symptom_parts = [p for p in [self.symptom, self.false_positive] if p]
        if symptom_parts:
            minis.append(" ".join(symptom_parts))
        # 保证至少 2 个 mini chunk
        if len(minis) < 2:
            minis = [minis[0] if minis else self.pattern_id] * 2
        return minis

    def validate(self) -> list[str]:
        """返回字段校验错误列表，空列表表示通过。"""
        errors: list[str] = []
        if not self.pattern_id or not str(self.pattern_id).strip():
            errors.append("pattern_id 不能为空")
        if not self.component or not str(self.component).strip():
            errors.append("component 不能为空")
        if not self.log_fingerprint:
            errors.append("log_fingerprint 不能为空")
        if self.severity and self.severity.lower() not in SEVERITY_LEVELS:
            errors.append(
                f"severity 必须是 {', '.join(sorted(SEVERITY_LEVELS))} 之一"
            )
        return errors
