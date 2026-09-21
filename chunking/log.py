"""日志专用分块策略

以 Drain 模板为最小分块单元，实现日志文本的语义分块。
每个 Drain 模板对应一个 chunk，metadata 包含模板统计信息。
支持跨模板上下文关联（基于时间窗口合并相邻模板）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEntry:
    """单条日志记录。"""
    line: str
    template_id: int = 0
    template: str = ""
    timestamp: int = 0
    source_dir: str = ""
    agent_id: str = ""


@dataclass
class LogChunk:
    """日志分块结果。一个 Drain 模板对应一个 chunk。"""
    template_id: int
    template: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    mini_chunk_texts: list[str] = field(default_factory=list)
    source_dir: str = ""
    agent_id: str = ""
    log_level: str = ""
    size: int = 0
    first_seen: int = 0
    last_seen: int = 0
    # 跨模板上下文关联
    related_template_ids: list[int] = field(default_factory=list)


def _detect_log_level(text: str) -> str:
    """检测日志级别。"""
    upper = text.upper()
    if any(kw in upper for kw in ("ERROR", "FATAL", "CRITICAL")):
        return "ERROR"
    if "WARN" in upper:
        return "WARN"
    return "INFO"


class LogChunker:
    """日志专用分块器：以 Drain 模板为最小分块单元。"""

    def __init__(self, max_samples: int = 10, context_window_sec: int = 300):
        """
        Args:
            max_samples: 每个 chunk 保留的最大样本日志行数
            context_window_sec: 跨模板上下文关联的时间窗口（秒）
        """
        self.max_samples = max_samples
        self.context_window_sec = context_window_sec

    def chunk_by_template(
        self,
        entries: list[LogEntry],
        template_stats: dict[int, dict[str, Any]] | None = None,
    ) -> list[LogChunk]:
        """按 Drain 模板分块。

        Args:
            entries: 日志条目列表（需包含 template_id 和 template）
            template_stats: 模板统计信息 {template_id: {size, first_seen, last_seen}}

        Returns:
            按模板分块的 LogChunk 列表
        """
        if template_stats is None:
            template_stats = {}

        # 按模板分组
        template_entries: dict[int, list[LogEntry]] = {}
        for entry in entries:
            tid = entry.template_id
            if tid <= 0:
                continue
            template_entries.setdefault(tid, []).append(entry)

        # 构建每个模板的 chunk
        chunks: list[LogChunk] = []
        for tid, group in template_entries.items():
            template_str = group[0].template if group else ""
            source_dir = group[0].source_dir if group else ""
            agent_id = group[0].agent_id if group else ""

            # 取最近的 N 条样本
            samples = group[:self.max_samples]
            sample_lines = [e.line for e in samples]

            # 构建 content: 模板字符串 + 样本日志行
            content_parts = [f"模板#{tid}: {template_str}"]
            if sample_lines:
                content_parts.append("\n样本日志:")
                for line in sample_lines:
                    content_parts.append(f"  {line}")
            content = "\n".join(content_parts)

            # 从统计信息中获取 size/first_seen/last_seen
            stats = template_stats.get(tid, {})
            size = stats.get("size", len(group))
            first_seen = stats.get("first_seen", min((e.timestamp for e in group), default=0))
            last_seen = stats.get("last_seen", max((e.timestamp for e in group), default=0))

            # 每条样本日志行独立生成 mini_chunk
            mini_chunks = [e.line for e in samples]

            chunks.append(LogChunk(
                template_id=tid,
                template=template_str,
                content=content,
                metadata={
                    "agent_id": agent_id,
                    "source_dir": source_dir,
                    "log_level": _detect_log_level(template_str),
                    "template_id": str(tid),
                    "first_seen": str(first_seen),
                    "last_seen": str(last_seen),
                    "size": str(size),
                },
                mini_chunk_texts=mini_chunks,
                source_dir=source_dir,
                agent_id=agent_id,
                log_level=_detect_log_level(template_str),
                size=size,
                first_seen=first_seen,
                last_seen=last_seen,
            ))

        # 跨模板上下文关联：同 source_dir + 时间窗口内的模板归为一组
        if self.context_window_sec > 0:
            self._link_related_chunks(chunks)

        # 按 size 降序排列
        chunks.sort(key=lambda c: c.size, reverse=True)
        return chunks

    def _link_related_chunks(self, chunks: list[LogChunk]) -> None:
        """关联时间窗口内同 source_dir 的模板。"""
        # 按 (agent_id, source_dir) 分组
        groups: dict[str, list[LogChunk]] = {}
        for chunk in chunks:
            key = f"{chunk.agent_id}|{chunk.source_dir}"
            groups.setdefault(key, []).append(chunk)

        for group_chunks in groups.values():
            # 按 first_seen 排序
            group_chunks.sort(key=lambda c: c.first_seen)

            # 在时间窗口内关联
            for i, chunk in enumerate(group_chunks):
                for j, other in enumerate(group_chunks):
                    if i == j:
                        continue
                    if chunk.first_seen > 0 and other.first_seen > 0:
                        time_diff = abs(chunk.first_seen - other.first_seen)
                        if time_diff <= self.context_window_sec:
                            if other.template_id not in chunk.related_template_ids:
                                chunk.related_template_ids.append(other.template_id)

    def chunk_to_index_data(self, chunk: LogChunk) -> dict[str, Any]:
        """将 LogChunk 转换为 /api/index 请求体。"""
        return {
            "content": chunk.content,
            "metadata": chunk.metadata,
            "document_id": f"log_template_{chunk.agent_id}_{chunk.template_id}",
        }
