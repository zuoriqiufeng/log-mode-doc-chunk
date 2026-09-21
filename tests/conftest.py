"""pytest 全局配置：把项目根目录加入 sys.path，并提供公共 fixture。

项目源码使用 `from models import ...` 这样的顶层导入（依赖项目根目录在 sys.path 中），
因此测试也必须先完成同样的路径注入，否则 import 会失败。
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SAMPLES_DIR = os.path.join(PROJECT_ROOT, "word")


@pytest.fixture(scope="session")
def project_root() -> str:
    """项目根目录绝对路径。"""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def samples_dir() -> str:
    """样例文档目录（word/）。"""
    return SAMPLES_DIR


@pytest.fixture
def sample_file(samples_dir):
    """按文件名取 word/ 下的样例文件路径，缺失时跳过用例。"""

    def _get(name: str) -> str:
        path = os.path.join(samples_dir, name)
        if not os.path.exists(path):
            pytest.skip(f"样例文件不存在: {path}")
        return path

    return _get
