#!/usr/bin/env python3
"""退化块审计：扫描 Qdrant collection，统计分块退化指标（只读）。

对应 bkn 的 exact-term-visibility-design.md §5.2 / §6：
- 超长标准块数：非 large、非 mini 的块中 content 长度 > standard-max（默认 2048）
- 超限 mini 窗口数：父块 mini_chunk_texts 中长度 > mini-max（默认 600）的片数；
  独立 mini point 中 content 超限的个数单独计
- 退化块清单：mini_chunk_count == 1 且 content 超限的标准块（mini 缩窗不可用）

重灌后本脚本应报告三项全零（退化块清单为空）。

用法：
  python audit_chunk_degeneration.py                          # 扫 qdrant.yml 配置连接下的全部 collection
  python audit_chunk_degeneration.py --collection i2stream_collection
  python audit_chunk_degeneration.py --json /tmp/degen.json   # 另存 JSON 报告
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def summarize(
    payloads: list[dict[str, Any]],
    standard_max: int = 2048,
    mini_max: int = 600,
) -> dict[str, Any]:
    """对一批 Qdrant payload 做退化统计（纯函数，供 pytest 直接调用）。"""
    oversize_standard: list[dict[str, Any]] = []
    mini_windows: list[dict[str, Any]] = []
    oversize_mini_points: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []

    for p in payloads:
        doc_id = p.get("document_id", "")
        chunk_id = p.get("chunk_id", -1)
        content = p.get("content") or ""

        if p.get("is_mini_chunk"):
            if len(content) > mini_max:
                oversize_mini_points.append(
                    {
                        "document_id": doc_id,
                        "chunk_id": chunk_id,
                        "mini_index": p.get("mini_chunk_index"),
                        "length": len(content),
                    }
                )
            continue

        if p.get("is_large_chunk"):
            continue  # 大块按设计合并多个块，天然超长

        if len(content) > standard_max:
            oversize_standard.append(
                {
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "chunk_level": p.get("chunk_level", ""),
                    "length": len(content),
                }
            )

        over_lengths = [
            len(t) for t in (p.get("mini_chunk_texts") or []) if len(t) > mini_max
        ]
        if over_lengths:
            mini_windows.append(
                {
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "window_count": len(over_lengths),
                    "max_length": max(over_lengths),
                }
            )

        if (p.get("mini_chunk_count") or 0) == 1 and len(content) > mini_max:
            degraded.append(
                {"document_id": doc_id, "chunk_id": chunk_id, "length": len(content)}
            )

    return {
        "counts": {
            "points": len(payloads),
            "oversize_standard": len(oversize_standard),
            "blocks_with_oversize_mini_windows": len(mini_windows),
            "oversize_mini_windows": sum(w["window_count"] for w in mini_windows),
            "oversize_mini_points": len(oversize_mini_points),
            "degraded_blocks": len(degraded),
        },
        "oversize_standard": oversize_standard,
        "blocks_with_oversize_mini_windows": mini_windows,
        "oversize_mini_points": oversize_mini_points,
        "degraded_blocks": degraded,
    }


def format_report(summary: dict[str, Any], scope: str = "") -> str:
    """把 summarize 的结果格式化为人读报告。"""
    counts = summary["counts"]
    scope_suffix = f"（{scope}）" if scope else ""
    lines = [
        f"退化块审计{scope_suffix}",
        f"  扫描 point 数: {counts['points']}",
        f"  超长标准块: {counts['oversize_standard']}",
        f"  含超限 mini 窗口的块: {counts['blocks_with_oversize_mini_windows']}"
        f"（窗口 {counts['oversize_mini_windows']} 个）",
        f"  超限 mini point: {counts['oversize_mini_points']}",
        f"  退化块（mini 缩窗失效）: {counts['degraded_blocks']}",
    ]
    for item in summary["degraded_blocks"][:10]:
        lines.append(
            f"    - {item['document_id']}#{item['chunk_id']} len={item['length']}"
        )
    if counts["degraded_blocks"] > 10:
        lines.append(f"    … 还有 {counts['degraded_blocks'] - 10} 个退化块")
    return "\n".join(lines)


def _scroll_all(client: Any, collection: str, batch: int = 1000) -> list[dict[str, Any]]:
    """分页全量读取一个 collection 的 payload（只读）。"""
    payloads: list[dict[str, Any]] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=batch,
            offset=offset,
            with_payload=True,
            with_vector=False,
        )
        payloads.extend([p.payload or {} for p in points])
        if offset is None:
            return payloads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="退化块审计：扫描 Qdrant collection，统计超长标准块/超限 mini/退化块清单（只读）",
    )
    parser.add_argument(
        "--collection",
        action="append",
        default=None,
        help="只扫指定 collection（可多次；缺省扫全部）",
    )
    parser.add_argument(
        "--standard-max", type=int, default=2048, help="标准块字符上限（默认 2048）"
    )
    parser.add_argument(
        "--mini-max", type=int, default=600, help="mini 片字符上限（默认 600）"
    )
    parser.add_argument("--json", dest="json_path", default=None, help="另存 JSON 报告到文件")
    args = parser.parse_args(argv)

    from vector_store import create_vector_store

    store = create_vector_store()
    client = store._client
    collections = args.collection or [c.name for c in client.get_collections().collections]

    result: dict[str, Any] = {"collections": {}, "totals": None}
    totals: dict[str, int] = {}
    for name in collections:
        payloads = _scroll_all(client, name)
        summary = summarize(payloads, args.standard_max, args.mini_max)
        print(format_report(summary, scope=name))
        print()
        result["collections"][name] = summary
        for key, value in summary["counts"].items():
            totals[key] = totals.get(key, 0) + value
    result["totals"] = totals
    print(f"合计: {json.dumps(totals, ensure_ascii=False)}")

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"JSON 报告已写入: {args.json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
