"""Markdown 提取器：保留标题层级、代码块、解析内嵌图片。"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from extractors.base import DocumentExtractor


# 远程图片下载限制
MAX_REMOTE_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
REMOTE_IMAGE_TIMEOUT = 30  # 秒


# 图片占位符模板，index 对应 images 列表中的顺序（无下划线，避免被 Markdown 斜体规则误处理）
_IMAGE_PLACEHOLDER = "【PIC:{index}】"


class MarkdownExtractor(DocumentExtractor):
    """Markdown 提取器。

    处理规则：
    - 保留标题层级（转换为 【H1】/【H2】/... 标记）
    - 代码块保留完整内容，并用 [Code Block] 边界包裹
    - 解析 ![alt](path) 内嵌图片，加载图片文件 bytes
    - 其他 Markdown 标记符号做清洗
    """

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()

        text, images = self._extract_with_images(file_path, raw)
        metadata = self._extract_frontmatter(raw)

        return text, metadata, images

    def _extract_frontmatter(self, content: str) -> dict[str, Any]:
        """提取 YAML frontmatter 中的 title。"""
        metadata: dict[str, Any] = {}
        if content.startswith("---"):
            frontmatter_end = content.find("---", 3)
            if frontmatter_end != -1:
                fm = content[3:frontmatter_end]
                title_match = re.search(r"^title:\s*(.+)$", fm, re.MULTILINE)
                if title_match:
                    metadata["Title"] = title_match.group(1).strip()
        return metadata

    def _extract_with_images(
        self, file_path: str, content: str
    ) -> tuple[str, list[tuple[bytes, str]]]:
        """提取文本并加载内嵌图片，返回 (text, images)。

        文本中图片位置用 [EMBEDDED_IMAGE:index] 占位，index 与 images 列表顺序一致。
        """
        base_dir = os.path.dirname(os.path.abspath(file_path))
        images: list[tuple[bytes, str]] = []

        # 1. 先提取代码块，避免代码块里的图片语法被误解析
        code_blocks: list[str] = []

        def _collect_code_block(match: re.Match) -> str:
            code = match.group(1).strip()
            code_blocks.append(code)
            return f"\n[Code Block]\n{code}\n[Code Block End]\n"

        content = re.sub(
            r"```(?:\w+)?\n([\s\S]*?)```",
            _collect_code_block,
            content,
        )

        # 2. 提取图片并加载文件
        def _collect_image(match: re.Match) -> str:
            alt = match.group(1).strip()
            src = match.group(2).strip()
            idx = len(images)

            # 远程图片下载
            if src.startswith("http://") or src.startswith("https://"):
                try:
                    req = Request(src, headers={"User-Agent": "Mozilla/5.0"})
                    with urlopen(req, timeout=REMOTE_IMAGE_TIMEOUT) as resp:
                        content_length = resp.headers.get("Content-Length")
                        if content_length and int(content_length) > MAX_REMOTE_IMAGE_SIZE:
                            print(f"[WARN] 远程图片过大跳过 {src}")
                            return f"[Image: {alt} ({src})]"
                        image_bytes = resp.read(MAX_REMOTE_IMAGE_SIZE)
                        # 如果还有剩余数据，说明超过限制
                        if resp.read(1):
                            print(f"[WARN] 远程图片过大跳过 {src}")
                            return f"[Image: {alt} ({src})]"
                    images.append((image_bytes, os.path.basename(src.split("?")[0]) or f"image_{idx}.png"))
                    return _IMAGE_PLACEHOLDER.format(index=idx)
                except Exception as e:
                    print(f"[WARN] 远程图片下载失败 {src}: {e}")
                    return f"[Image: {alt} ({src})]"

            image_path = src if os.path.isabs(src) else os.path.join(base_dir, src)
            image_path = os.path.normpath(image_path)

            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                images.append((image_bytes, os.path.basename(image_path)))
                return _IMAGE_PLACEHOLDER.format(index=idx)
            except Exception as e:
                print(f"[WARN] Markdown 内嵌图片加载失败 {src}: {e}")
                return f"[Image: {alt} (load failed)]"

        content = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            _collect_image,
            content,
        )

        # 3. 清洗其他 Markdown 标记，但保留标题层级
        text = self._clean_markdown(content)

        return text, images

    def _clean_markdown(self, text: str) -> str:
        # 移除 YAML frontmatter
        if text.startswith("---"):
            frontmatter_end = text.find("---", 3)
            if frontmatter_end != -1:
                text = text[frontmatter_end + 3:]

        # 保留标题层级：# 标题 -> 【H1】标题
        def _heading_repl(match: re.Match) -> str:
            level = len(match.group(1))
            title = match.group(2).strip()
            return f"【H{level}】{title}"

        text = re.sub(r"^(#{1,6})\s+(.+)$", _heading_repl, text, flags=re.MULTILINE)

        # 移除链接标记，保留文本
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # 移除纯 URL 链接（非图片）
        text = re.sub(r"<([^>]+)>", r"\1", text)

        # 移除粗体/斜体标记
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)

        # 移除引用标记
        text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
        # 移除水平线
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # 移除 Markdown 表格分隔行
        text = re.sub(r"^\|?[-:\s|]+\|?\s*$", "", text, flags=re.MULTILINE)
        # 将 Markdown 表格行中的 | 替换为 \t
        text = re.sub(
            r"^\|(.+)\|\s*$",
            lambda m: m.group(1).replace("|", "\t"),
            text,
            flags=re.MULTILINE,
        )

        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
