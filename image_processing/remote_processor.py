"""远程图片处理器：使用 OpenAI Vision API 理解图片内容。"""

from __future__ import annotations

import time
from typing import Any

from image_processing.base import BaseImageProcessor
from image_processing.config import ImageProcessorConfig
from image_processing.utils import encode_image_to_base64, is_too_small


# 可重试的异常类型
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = ()


def _get_retryable_exceptions() -> tuple[type[Exception], ...]:
    """懒加载 OpenAI 异常类型。"""
    global _RETRYABLE_EXCEPTIONS
    if not _RETRYABLE_EXCEPTIONS:
        try:
            import openai
            _RETRYABLE_EXCEPTIONS = (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.InternalServerError,
                openai.RateLimitError,
            )
        except ImportError:
            _RETRYABLE_EXCEPTIONS = (Exception,)
    return _RETRYABLE_EXCEPTIONS


class OpenAIVisionProcessor(BaseImageProcessor):
    """基于 OpenAI Vision 的远程图片处理器。

    同时提取图片文字并生成简短描述，适合对理解质量要求高且可接受 API 费用的场景。
    """

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        prompt: str | None = None,
    ) -> None:
        self._model_name = model_name or ImageProcessorConfig.MODEL_NAME
        self.api_key = api_key or ImageProcessorConfig.API_KEY
        self.base_url = base_url or ImageProcessorConfig.BASE_URL
        self.prompt = prompt or ImageProcessorConfig.REMOTE_PROMPT
        self._client: Any | None = None

    @property
    def backend_name(self) -> str:
        return "openai_vision"

    @property
    def model_name(self) -> str | None:
        return self._model_name

    def _get_client(self) -> Any:
        """懒加载 OpenAI client。"""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise RuntimeError(
                    "openai 包未安装，请运行: pip install openai"
                ) from e

            if not self.api_key or self.api_key == "sk-your-key-here":
                raise RuntimeError("未配置 OPENAI_API_KEY，无法使用远程图片处理")

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def process(self, image_bytes: bytes, filename: str = "") -> str:
        """调用 OpenAI Vision API 处理图片，支持失败重试。"""
        if is_too_small(
            image_bytes,
            ImageProcessorConfig.MIN_IMAGE_WIDTH,
            ImageProcessorConfig.MIN_IMAGE_HEIGHT,
        ):
            return ""

        try:
            base64_image = encode_image_to_base64(image_bytes)
        except Exception as e:
            print(f"[WARN] 图片 base64 编码失败 ({filename}): {e}")
            return ""

        max_retries = 3
        base_delay = 1.0
        retryable_errors = _get_retryable_exceptions()

        for attempt in range(max_retries):
            try:
                client = self._get_client()
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": self.prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{base64_image}",
                                    },
                                },
                            ],
                        }
                    ],
                    max_tokens=1600,  # reasoning 模型需预算思考 token，过小会返回空 content
                )
                content = response.choices[0].message.content or ""
                content = content.strip()
                # API 偶发返回空内容，也视为可重试
                if not content:
                    raise RuntimeError("API 返回空内容")
                return content
            except retryable_errors as e:
                if attempt == max_retries - 1:
                    print(f"[WARN] OpenAI Vision 处理失败 ({filename}): {e}")
                    return ""
                delay = base_delay * (2 ** attempt)
                print(
                    f"[WARN] OpenAI Vision 处理失败 ({filename})，"
                    f"{delay:.1f}s 后重试 ({attempt + 1}/{max_retries}): {e}"
                )
                time.sleep(delay)
            except Exception as e:
                # 非网络类异常（如 API 返回空内容）也重试一次
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(
                        f"[WARN] OpenAI Vision 返回异常 ({filename})，"
                        f"{delay:.1f}s 后重试 ({attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(delay)
                else:
                    print(f"[WARN] OpenAI Vision 处理失败 ({filename}): {e}")
                    return ""
        return ""
