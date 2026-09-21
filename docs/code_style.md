# chunk 代码风格

## 语言版本

- Python 3.9+
- 源码注释和 CLI 输出使用中文。

## 数据模型

- 使用 `@dataclass`。
- 文件顶部使用 `from __future__ import annotations` 支持前向引用。

## 类型提示

- 使用 `str | None`（union syntax）。
- 使用 `list[X]`、`dict[str, Any]` 等小写泛型。

## 导入顺序

```python
from __future__ import annotations  # 始终第一

# stdlib
# third-party
# local
```

## 文档字符串

模块级 docstring 应引用对应的 Onyx 源文件。

## 测试与验证

- 测试用 pytest，放在 `tests/`，文件名 `test_*.py`。
- 只测不依赖外部服务的纯逻辑；涉及模型下载、Qdrant 实连、OCR/Vision 的部分靠手工冒烟（见 `docs/build.md` 的「验证」一节）。
- 用例名用中文描述意图，例如 `test_large_chunks_carry_no_mini_chunks`。
- 没有配置 linter/formatter。

## 通用原则

- 遵循现有代码模式。
- 保持中文注释和输出。
