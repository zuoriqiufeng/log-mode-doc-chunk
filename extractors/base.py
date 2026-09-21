"""文档提取器抽象基类。"""

from __future__ import annotations

import abc
from typing import Any


class DocumentExtractor(abc.ABC):
    """文档提取器基类"""

    @abc.abstractmethod
    def extract(
        self, file_path: str
    ) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]:
        """
        提取文档内容。

        Returns:
            (text, metadata, images)
            - text: 文档纯文本内容
            - metadata: 文档元数据字典
            - images: 提取的嵌入图片列表 [(bytes, filename), ...]
        """
        raise NotImplementedError
