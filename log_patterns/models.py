"""日志模式库数据模型。

参考: i2stream-bkn 项目《Qdrant 日志模式库设计》(doc/log-analysis/qdrant-log-pattern-library-design.md)
字段口径: 日志数据模型 v2.1（17 字段）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


SEVERITY_LEVELS = {"critical", "high", "medium", "low"}

# iaback / iawork 仅 9.0 前版本存在，保留是为了历史数据可入库
COMPONENTS = {
    "iatrack",
    "iadumper",
    "ialoader",
    "iahelper",
    "iamonitor",
    "iadiff",
    "iaproxy",
    "iaback",
    "iawork",
}

# 与 i2stream-bkn/plugin/error_semantics.yaml 的 dimension 枚举一致（去掉 "dimension:" 前缀）
DIMENSIONS = {
    "log_readable",
    "state_machine",
    "permission",
    "connectivity",
    "resource",
    "consistency",
    "time_sync",
    "unknown",
}

GRADES = {"confirmed", "clue"}

DB_TYPES = {
    "oracle",
    "mysql",
    "postgresql",
    "sqlserver",
    "db2",
    "db2_as400",
    "oceanbase",
    "yashandb",
    "gaussdb",
    "dm",
    "vastbase",
    "kingbase",
    "analyticdb",
    "opengauss",
    "tdsql",
    "mariadb",
    "polardb_x",
    "通用",
}

# kafka / hive / starrocks 为预留值，未放行
TARGET_TYPES = {"datahub", "doris", "hbase"}

_UPDATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class LogPattern:
    """单条日志模式条目。

    字段与日志数据模型 v2.1 对齐。
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
    target_types: list[str] = field(default_factory=list)
    dimension: str = ""
    grade: str = ""
    counter_evidence: str = ""
    false_positive: str = ""
    log_samples: list[str] = field(default_factory=list)
    source_note: str = ""
    updated_at: str = field(default_factory=lambda: date.today().isoformat())
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
        if self.target_types:
            lines.append(f"Target types: {', '.join(self.target_types)}")
        if self.dimension:
            lines.append(f"Dimension: {self.dimension}")
        if self.grade:
            lines.append(f"Grade: {self.grade}")
        if self.log_fingerprint:
            lines.append(f"Log fingerprint: {', '.join(self.log_fingerprint)}")
        if self.symptom:
            lines.append(f"Symptom: {self.symptom}")
        if self.false_positive:
            lines.append(f"False positive: {self.false_positive}")
        if self.counter_evidence:
            lines.append(f"Counter evidence: {self.counter_evidence}")
        if self.root_cause:
            lines.append(f"Root cause: {self.root_cause}")
        if self.remediation:
            lines.append("Remediation:")
            for step in self.remediation:
                lines.append(f"  - {step}")
        if self.log_samples:
            lines.append("Log samples:")
            for sample in self.log_samples:
                lines.append(f"  | {sample}")
        if self.source_note:
            lines.append(f"Source note: {self.source_note}")
        lines.append(f"Updated at: {self.updated_at}")
        return "\n".join(lines)

    def mini_texts(self) -> list[str]:
        """生成 2-4 个 mini chunk 文本。

        顺序：
        - mini-1: 日志特征指纹 + 真实日志原文（同为按日志文本匹配导向）
        - mini-2: 根因
        - mini-3: 处置要点
        - mini-4: 症状 + 误判提示 + 反证
        """
        minis: list[str] = []
        fp_parts = [self.fingerprint_text, " ".join(self.log_samples)]
        fp = " ".join(p for p in fp_parts if p).strip()
        if fp:
            minis.append(fp)
        if self.root_cause:
            minis.append(self.root_cause)
        if self.remediation:
            minis.append(" ".join(self.remediation))
        symptom_parts = [p for p in [self.symptom, self.false_positive, self.counter_evidence] if p]
        if symptom_parts:
            minis.append(" ".join(symptom_parts))
        # 保证至少 2 个 mini chunk
        if len(minis) < 2:
            minis = [minis[0] if minis else self.pattern_id] * 2
        return minis

    def validate(self) -> list[str]:
        """返回字段校验错误列表，空列表表示通过。

        按 v2.1 口径严格校验：必填缺失与枚举违规都会被挡下。
        """
        errors: list[str] = []

        def _check_enum(name: str, values: list[str], allowed: set[str]) -> None:
            for v in values:
                if str(v).strip().lower() not in allowed:
                    errors.append(
                        f"{name} 含非法值 '{v}'，必须是 {', '.join(sorted(allowed))} 之一"
                    )

        if not self.pattern_id or not str(self.pattern_id).strip():
            errors.append("pattern_id 不能为空")
        if not self.component or not str(self.component).strip():
            errors.append("component 不能为空")
        elif str(self.component).strip().lower() not in COMPONENTS:
            errors.append(
                f"component '{self.component}' 必须是 {', '.join(sorted(COMPONENTS))} 之一"
            )
        if not self.severity or not str(self.severity).strip():
            errors.append("severity 不能为空")
        elif self.severity.lower() not in SEVERITY_LEVELS:
            errors.append(
                f"severity 必须是 {', '.join(sorted(SEVERITY_LEVELS))} 之一"
            )
        if len(self.log_fingerprint) < 2:
            errors.append("log_fingerprint 至少需要 2 个特征词")
        if not self.dimension or not str(self.dimension).strip():
            errors.append("dimension 不能为空")
        elif str(self.dimension).strip().lower() not in DIMENSIONS:
            errors.append(
                f"dimension '{self.dimension}' 必须是 {', '.join(sorted(DIMENSIONS))} 之一"
            )
        if not self.grade or not str(self.grade).strip():
            errors.append("grade 不能为空")
        elif str(self.grade).strip().lower() not in GRADES:
            errors.append(
                f"grade '{self.grade}' 必须是 {', '.join(sorted(GRADES))} 之一"
            )
        if self.db_types:
            _check_enum("db_types", self.db_types, DB_TYPES)
        if self.target_types:
            _check_enum("target_types", self.target_types, TARGET_TYPES)
        overlap = {
            str(v).strip().lower() for v in self.db_types
        } & {str(v).strip().lower() for v in self.target_types}
        if overlap:
            errors.append(
                f"db_types 与 target_types 不得交叉（同一值 '{sorted(overlap)[0]}' 只能出现在一边）"
            )
        if not self.updated_at or not _UPDATED_AT_RE.match(str(self.updated_at).strip()):
            errors.append("updated_at 必须是 YYYY-MM-DD 格式")
        return errors
