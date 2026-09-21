#!/usr/bin/env python3
"""日志模式导入便捷入口。

等价于: python -m log_patterns.cli
"""

from __future__ import annotations

import sys

from log_patterns.cli import main

if __name__ == "__main__":
    sys.exit(main())
