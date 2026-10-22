"""审计脚本纯逻辑测试：退化统计与报告格式化（不碰网络）。"""

from __future__ import annotations

from audit_chunk_degeneration import format_report, summarize


def _payload(**overrides) -> dict:
    base = {
        "document_id": "doc1",
        "chunk_id": 0,
        "content": "short",
        "is_mini_chunk": False,
        "is_large_chunk": False,
        "chunk_level": "standard",
        "mini_chunk_count": 0,
        "mini_chunk_texts": [],
    }
    base.update(overrides)
    return base


class TestSummarize:
    def test_混合样本计数与清单正确(self):
        payloads = [
            _payload(),  # 正常标准块
            _payload(chunk_id=1, content="x" * 3000),  # 超长标准块
            _payload(chunk_id=2, content="y" * 9000, is_large_chunk=True, chunk_level="large"),
            _payload(chunk_id=3, content="a" * 700, mini_chunk_count=1),  # 退化块
            _payload(
                chunk_id=3,
                content="b" * 700,
                is_mini_chunk=True,
                chunk_level="mini",
                mini_chunk_index=0,
            ),  # 超限 mini point
            _payload(
                chunk_id=4,
                content="ok",
                mini_chunk_count=2,
                mini_chunk_texts=["m" * 650, "s"],
            ),  # 超限 mini 窗口
        ]
        summary = summarize(payloads)
        counts = summary["counts"]

        assert counts["points"] == 6
        assert counts["oversize_standard"] == 1
        assert counts["blocks_with_oversize_mini_windows"] == 1
        assert counts["oversize_mini_windows"] == 1
        assert counts["oversize_mini_points"] == 1
        assert counts["degraded_blocks"] == 1
        assert summary["degraded_blocks"][0]["chunk_id"] == 3

    def test_全合规返回全零(self):
        # content 恰好等于上限不算超限（严格大于才计数）
        summary = summarize(
            [
                _payload(content="c" * 2048),
                _payload(chunk_id=1, content="m" * 600, mini_chunk_count=1),
            ]
        )
        counts = summary["counts"]
        assert counts["oversize_standard"] == 0
        assert counts["oversize_mini_points"] == 0
        assert counts["blocks_with_oversize_mini_windows"] == 0
        assert counts["degraded_blocks"] == 0


class TestFormatReport:
    def test_报告包含关键计数与退化清单(self):
        summary = summarize(
            [_payload(chunk_id=3, content="a" * 700, mini_chunk_count=1)]
        )
        report = format_report(summary, scope="demo_collection")

        assert "demo_collection" in report
        assert "超长标准块: 0" in report
        assert "退化块（mini 缩窗失效）: 1" in report
        assert "doc1#3" in report
