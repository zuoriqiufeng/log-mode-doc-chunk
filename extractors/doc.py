"""旧版 Word .doc 提取器（OLE2 格式，参考 Onyx 对旧格式文档的处理）。

.doc 是 OLE2 复合文档格式，python-docx 仅支持 .docx（Office Open XML）。
本提取器通过 olefile 解析 OLE2 结构，从 WordDocument 流的 CLX piece table
中提取 Unicode/ANSI 文本，无需依赖 libreoffice 或 antiword 等外部工具。
"""

from __future__ import annotations

import os
import struct
from typing import Any

from extractors.base import DocumentExtractor


class DocExtractor(DocumentExtractor):
    """旧版 Word .doc 文件提取器（OLE2 格式）。"""

    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        import olefile

        if not olefile.isOleFile(file_path):
            raise ValueError(f"文件不是有效的 OLE2 格式: {file_path}")

        ole = olefile.OleFileIO(file_path)

        try:
            text = self._extract_text(ole)
            metadata = self._extract_metadata(ole)
            images: list[tuple[bytes, str]] = []
        finally:
            ole.close()

        return text, metadata, images

    def _extract_text(self, ole: olefile.OleFileIO) -> str:
        """从 WordDocument 流的 CLX piece table 中提取文本。"""
        word_stream = ole.openstream("WordDocument").read()

        # 读取 FIB flags
        flags = struct.unpack_from("<H", word_stream, 0x000A)[0]

        # 确定使用哪个 Table 流
        fWhichTblStm = (flags >> 9) & 1
        table_name = f"{fWhichTblStm}Table"
        if not ole.exists(table_name):
            return self._extract_text_fallback(word_stream)
        table_stream = ole.openstream(table_name).read()

        # 计算 fibRgFcLcb 偏移
        csw = struct.unpack_from("<H", word_stream, 32)[0]
        fibRgW_offset = 34
        cslw = struct.unpack_from("<H", word_stream, fibRgW_offset + csw * 2)[0]
        fibRgLw_offset = fibRgW_offset + csw * 2 + 2
        cbRgFcLcb = struct.unpack_from("<H", word_stream, fibRgLw_offset + cslw * 4)[0]
        fibRgFcLcb_offset = fibRgLw_offset + cslw * 4 + 2

        # fcClx 在 fibRgFcLcb97 中是第 33 个条目
        clx_entry_idx = 33
        entry_offset = fibRgFcLcb_offset + clx_entry_idx * 8
        if entry_offset + 8 > len(word_stream):
            return self._extract_text_fallback(word_stream)

        fcClx = struct.unpack_from("<I", word_stream, entry_offset)[0]
        lcbClx = struct.unpack_from("<I", word_stream, entry_offset + 4)[0]

        if fcClx == 0 or lcbClx == 0 or fcClx + lcbClx > len(table_stream):
            return self._extract_text_fallback(word_stream)

        clx = table_stream[fcClx : fcClx + lcbClx]

        # 解析 CLX：跳过 Prc（0x01），找 Pcdt（0x02）
        pos = 0
        while pos < len(clx):
            clxt = clx[pos]
            if clxt == 0x02:  # Pcdt
                pos += 1
                lcb = struct.unpack_from("<I", clx, pos)[0]
                pos += 4
                return self._parse_plc_pcd(clx[pos : pos + lcb], word_stream)
            elif clxt == 0x01:  # Prc
                pos += 1
                cbGrpprl = struct.unpack_from("<H", clx, pos)[0]
                pos += 2 + cbGrpprl
            else:
                break

        return self._extract_text_fallback(word_stream)

    def _parse_plc_pcd(self, plc_pcd: bytes, word_stream: bytes) -> str:
        """解析 PlcPcd（piece table）提取文本。"""
        # PlcPcd: (n+1) 个 CP（各 4 bytes）+ n 个 PCD（各 8 bytes）
        # (n+1)*4 + n*8 = len => 12n = len - 4 => n = (len-4)//12
        lcb = len(plc_pcd)
        if lcb < 12:
            return ""

        n = (lcb - 4) // 12
        if n <= 0:
            return ""

        # 读取 CP 数组
        cps = [struct.unpack_from("<I", plc_pcd, i * 4)[0] for i in range(n + 1)]

        # 读取 PCD 并提取文本
        pcd_offset = (n + 1) * 4
        text_parts: list[str] = []

        for i in range(n):
            pcd_start = pcd_offset + i * 8
            if pcd_start + 8 > len(plc_pcd):
                break

            fc_value = struct.unpack_from("<I", plc_pcd, pcd_start + 2)[0]
            char_count = cps[i + 1] - cps[i]

            if char_count <= 0:
                continue

            # bit 30 为 0 表示 Unicode，为 1 表示压缩 ANSI
            is_unicode = (fc_value & 0x40000000) == 0
            fc = fc_value & 0x3FFFFFFF

            try:
                if is_unicode:
                    raw = word_stream[fc : fc + char_count * 2]
                    text = raw.decode("utf-16-le", errors="replace")
                else:
                    # 压缩格式：fc 需要除以 2
                    fc = fc // 2
                    raw = word_stream[fc : fc + char_count]
                    text = raw.decode("cp1252", errors="replace")
                text_parts.append(text)
            except Exception:
                continue

        full_text = "".join(text_parts)
        # 清理特殊字符：\r -> 换行，\x07 -> 删掉（表格单元格标记），
        # \x0C -> 换行（分页符），\x01 -> 删掉（域标记）
        full_text = (
            full_text.replace("\r", "\n")
            .replace("\x07", "")
            .replace("\x0C", "\n")
            .replace("\x01", "")
        )
        return full_text

    def _extract_text_fallback(self, word_stream: bytes) -> str:
        """当 CLX 解析失败时的后备方案：扫描 Unicode 文本区域。"""
        # 尝试从 WordDocument 流中查找可读的 Unicode 文本
        # 这不是精确解析，但能提取大部分文本
        text_parts: list[str] = []
        i = 0
        current: list[str] = []

        while i < len(word_stream) - 1:
            code = struct.unpack_from("<H", word_stream, i)[0]
            # CJK Unified Ideographs, common punctuation, ASCII printable
            if 0x20 <= code <= 0x7E or 0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F:
                current.append(chr(code))
            elif code == 0x000D or code == 0x000A:
                current.append("\n")
            else:
                if len(current) > 5:  # 只保留连续较长的文本片段
                    text_parts.append("".join(current))
                current = []
            i += 2

        if len(current) > 5:
            text_parts.append("".join(current))

        return "\n".join(text_parts)

    def _extract_metadata(self, ole: olefile.OleFileIO) -> dict[str, Any]:
        """从 OLE SummaryInformation 流提取元数据。"""
        metadata: dict[str, Any] = {}

        try:
            props = ole.getproperties("\x05SummaryInformation")
            # PIDSI_TITLE = 0x02, PIDSI_AUTHOR = 0x04
            if 0x02 in props and props[0x02]:
                val = str(props[0x02])
                # WPS 等软件可能写入包含 \x00 或非文本字符的元数据，截取第一个 \x00 之前的内容
                val = val.split("\x00")[0].strip()
                if val and val.isprintable():
                    metadata["Title"] = val
            if 0x04 in props and props[0x04]:
                val = str(props[0x04])
                val = val.split("\x00")[0].strip()
                if val and val.isprintable():
                    metadata["Author"] = val
        except Exception:
            pass

        return metadata
