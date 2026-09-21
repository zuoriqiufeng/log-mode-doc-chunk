"""HTML 提取器（参考 Onyx parse_html_page_basic + web_html_cleanup）"""

from __future__ import annotations

import re
from typing import Any

from extractors.base import DocumentExtractor


class HtmlExtractor(DocumentExtractor):
    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        import bs4

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        soup = bs4.BeautifulSoup(content, "lxml")

        # 提取标题
        title = None
        title_tag = soup.find("title")
        if title_tag and title_tag.text:
            title = title_tag.text.strip()

        # 移除脚本和样式
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()

        # 格式化文本
        text = self._format_soup(soup)

        metadata: dict[str, Any] = {}
        if title:
            metadata["Title"] = title

        return text, metadata, []

    def _format_soup(self, soup: Any) -> str:
        """将 BeautifulSoup 格式化为纯文本（参考 Onyx format_document_soup）"""
        import bs4

        text = ""
        in_table = False

        for e in soup.descendants:
            # 跳过 DOCTYPE 和注释
            if isinstance(e, bs4.Doctype) or isinstance(e, bs4.Comment):
                continue
            # 文本节点：NavigableString 是 str 的子类
            if isinstance(e, str):
                element_text = str(e)
                if in_table:
                    element_text = element_text.replace("\n", " ").strip()
                if element_text:
                    if text and not text[-1].isspace():
                        text += " "
                    text += element_text
                continue

            # 跳过非标签节点
            if not hasattr(e, "name"):
                continue

            if e.name == "table":
                in_table = True
            elif e.name == "p" or e.name == "div":
                text += "\n"
            elif e.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text += "\n"
            elif e.name == "br":
                text += "\n"
            elif e.name == "li":
                text += "\n- "
            elif e.name == "tr" and in_table:
                text += "\n"
            elif e.name in ("td", "th") and in_table:
                text += "\t"

        text = re.sub(r" +", " ", text)
        text = re.sub(r" +\n", "\n", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()
