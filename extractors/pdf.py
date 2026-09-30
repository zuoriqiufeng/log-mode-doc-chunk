"""PDF 提取器（参考 Onyx read_pdf_file）

在基础提取之外做两件 PDF 特有的事：

1. 页内折行重排（_reflow_page_text）：pypdf 按视觉行输出文本，若直接进分块器，
   SentenceChunker 会把折行当原子单元，chunk 接缝落在折行处、可能切进句子中间。
   这里先把被折断的行合并回句子/段落再返回。只做页内重排，不跨页合并
   （页边界视为段落边界，避免误连页眉/页脚）。
2. 图片占位符：按 docx.py 同款约定 emit 【PIC:{index}】（独立成段、放页尾），
   使 pipeline 的交错重建能生成 IMAGE Section。pypdf 无法可靠定位图片在页
   文本中的坐标，统一放页尾是已记录的取舍。
"""

from __future__ import annotations

import io
import re
from typing import Any

from extractors.base import DocumentExtractor

# 与 docx.py / markdown.py 同格式（docs/review_checklist.md「图片处理」节的要求）
_IMAGE_PLACEHOLDER = "【PIC:{index}】"

# 行尾终止标点（含紧随的引号/括号）：以这些字符结尾的行视为句末，不再向后合并。
# 逗号/顿号刻意不在其中——以「，」结尾的行正是被折断的行。
_TERMINAL_TAIL = "。．.!?！？；;：:…」』）)】\"'"

# 列表/标题起始：既不向外续行，也不被并入上一行（列表项、小节号保持独立）。
_LIST_PREFIX_RE = re.compile(
    r"^(?:[-–—•*·#>]|[0-9]{1,2}[.、)）]|[（(][0-9]{1,2}[)）])"
)

# 表格触发词与 utils.detect_and_parse_table 保持同一套
_TABLE_TRIGGER_RE = re.compile(r"(?i)(comparison\s+table|table:|表格)")
_TABLE_HEADER_WORDS = ("Connector", "Name", "ID")

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

# 宽度守卫：prev 行达到参考行宽（非空行长度 90 分位）的一定比例，
# 才视为「被折断的行」。表格单元格、题注等短行过不了这条。
_MIN_ABS_WIDTH = 16
_WIDTH_RATIO = 0.6


def _ends_terminal(line: str) -> bool:
    return bool(line) and line[-1] in _TERMINAL_TAIL


def _is_list_item(line: str) -> bool:
    return bool(_LIST_PREFIX_RE.match(line))


def _looks_like_table_caption(line: str) -> bool:
    """短表格触发行（题注/表头词）：不并入上一段，也不吸收后一行。"""
    s = line.strip()
    return len(s) <= 50 and (
        _TABLE_TRIGGER_RE.search(s) is not None or s in _TABLE_HEADER_WORDS
    )


def _reference_width(lines: list[str]) -> int:
    """参考行宽：非空行长度的 90 分位；行数太少时退化为最大值。"""
    widths = sorted(len(line) for line in lines if line)
    if not widths:
        return 0
    if len(widths) < 4:
        return widths[-1]
    return widths[(9 * len(widths) + 9) // 10 - 1]


def _join_lines(prev: str, cur: str) -> str:
    """拼接两行：英文断词去连字符；CJK 边界不加空格，两侧 ASCII 才补空格。"""
    if prev.endswith("-") and cur[:1].isascii() and cur[:1].isalpha():
        return prev[:-1] + cur
    if _CJK_RE.match(prev[-1]) or _CJK_RE.match(cur[:1]):
        return prev + cur
    return prev + " " + cur


def _table_zone(lines: list[str]) -> tuple[int, int] | None:
    """镜像 utils.detect_and_parse_table 的区域判定，返回保护区间 [start, end)。

    区间内的行在重排时保持一行一行的结构（不合并），保证重排后
    detect_and_parse_table 仍能收集到同样的表格行。收集不满 8 个短行时，
    与 utils 同样视为非表格，不设保护区。
    """
    start = -1
    for i, line in enumerate(lines):
        if _TABLE_TRIGGER_RE.search(line):
            start = i
            break
    if start == -1:
        for i in range(len(lines) - 3):
            if lines[i].strip() in _TABLE_HEADER_WORDS:
                start = max(0, i - 1)
                break
    if start == -1:
        return None

    collected = 0
    consecutive_short = 0
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        if not s:
            if consecutive_short >= 4:
                end = j
                break
            continue
        if len(s) <= 50:
            collected += 1
            consecutive_short += 1
        elif consecutive_short >= 8:
            end = j
            break
    if collected < 8:
        return None
    return start, end


def _reflow_page_text(text: str) -> str:
    """把一页的视觉折行合并回句子/段落（动机见模块 docstring）。

    规则（保守方向：宁可少合并，不破坏列表/表格结构）：
    - 仅当缓冲末行「无句末标点、非列表项、非题注、长度达到宽度守卫」，
      且当前行也非列表项/题注时，才并入当前段落；
    - 空行 = 段落边界；
    - 表格保护区（_table_zone）内的行原样按换行连接，绝不合并。
    """
    lines = [line.strip() for line in text.splitlines()]
    if not any(lines):
        return ""

    zone = _table_zone(lines)
    threshold = max(_MIN_ABS_WIDTH, int(_WIDTH_RATIO * _reference_width(lines)))

    paragraphs: list[str] = []
    cur: str | None = None

    def _flush() -> None:
        nonlocal cur
        if cur is not None:
            paragraphs.append(cur)
            cur = None

    i = 0
    while i < len(lines):
        if zone is not None and i == zone[0]:
            _flush()
            block = "\n".join(lines[zone[0] : zone[1]]).strip()
            if block:
                paragraphs.append(block)
            i = zone[1]
            continue
        line = lines[i]
        if not line:
            _flush()
        elif (
            cur is not None
            and not _ends_terminal(cur)
            and not _is_list_item(cur)
            and not _looks_like_table_caption(cur)
            and len(cur) >= threshold
            and not _is_list_item(line)
            and not _looks_like_table_caption(line)
        ):
            cur = _join_lines(cur, line)
        else:
            _flush()
            cur = line
        i += 1
    _flush()
    return "\n\n".join(paragraphs)


class PdfExtractor(DocumentExtractor):
    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        from pypdf import PdfReader

        metadata: dict[str, Any] = {}
        images: list[tuple[bytes, str]] = []

        with open(file_path, "rb") as f:
            reader = PdfReader(f)

            if reader.is_encrypted:
                try:
                    if reader.decrypt("") == 0:
                        return "", metadata, []
                except Exception:
                    return "", metadata, []

            # 元数据
            if reader.metadata is not None:
                for key, value in reader.metadata.items():
                    clean_key = key.lstrip("/")
                    if isinstance(value, str) and value.strip():
                        metadata[clean_key] = value
                    elif isinstance(value, list) and all(
                        isinstance(item, str) for item in value
                    ):
                        metadata[clean_key] = ", ".join(value)

            # 文本（页内折行重排）+ 图片（占位符追加在页尾）：
            # 单次页遍历，保证占位符序号与 images 严格对齐（同 docx.py 的约定：
            # 先取 len(images) 作序号，仅成功路径才追加 images 并记占位符）。
            page_texts: list[str] = []
            for page_num, page in enumerate(reader.pages):
                page_text = _reflow_page_text(page.extract_text() or "")
                placeholder_indices: list[int] = []
                for img_obj in page.images:
                    try:
                        from PIL import Image
                        image = Image.open(io.BytesIO(img_obj.data))
                        buf = io.BytesIO()
                        image.save(buf, format=image.format or "PNG")
                        img_bytes = buf.getvalue()
                        fmt = (image.format or "png").lower()
                        name = f"page_{page_num + 1}_image_{img_obj.name}.{fmt}"
                        placeholder_indices.append(len(images))
                        images.append((img_bytes, name))
                    except Exception:
                        pass
                if placeholder_indices:
                    # 占位符独立成段、放页尾；在 reflow 之后插入，不会被合并
                    placeholders = "\n\n".join(
                        _IMAGE_PLACEHOLDER.format(index=idx)
                        for idx in placeholder_indices
                    )
                    page_text = (
                        f"{page_text}\n\n{placeholders}" if page_text else placeholders
                    )
                page_texts.append(page_text)

            text = "\n\n".join(page_texts)

        return text, metadata, images
