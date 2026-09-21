#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档分块向量化平台 — 启动脚本

同时启动前端服务器（58001）和后端 API 服务器（58002）。
Ctrl+C 停止所有服务。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEB_DIR)

# 确保 venv 中的 Python 可用（优先 venv，其次 .venv）
VENV_PYTHON = os.path.join(PROJECT_ROOT, "venv", "bin", "python3")
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable


def main():
    print("=" * 60)
    print("文档分块向量化平台 — 启动")
    print("=" * 60)

    env = os.environ.copy()
    env["PYTHONPATH"] = PROJECT_ROOT

    # 启动后端 API 服务
    print("[1] 启动后端 API 服务 (端口 58002)...")
    backend = subprocess.Popen(
        [VENV_PYTHON, os.path.join(WEB_DIR, "app.py")],
        cwd=PROJECT_ROOT,
        env=env,
    )

    # 启动前端服务
    print("[2] 启动前端服务器 (端口 58001)...")
    frontend = subprocess.Popen(
        [VENV_PYTHON, os.path.join(WEB_DIR, "frontend.py")],
        cwd=PROJECT_ROOT,
        env=env,
    )

    def shutdown(signum, frame):
        print("\n正在停止服务...")
        frontend.terminate()
        backend.terminate()
        try:
            frontend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend.kill()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
        print("服务已停止")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("\n" + "=" * 60)
    print("服务已启动！")
    print(f"  前端页面: http://localhost:58001")
    print(f"  后端 API: http://localhost:58002")
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 60)

    # 等待任意子进程退出
    try:
        while True:
            ret = backend.poll()
            if ret is not None:
                print(f"后端进程已退出 (code={ret})")
                break
            ret = frontend.poll()
            if ret is not None:
                print(f"前端进程已退出 (code={ret})")
                break
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    shutdown(None, None)


if __name__ == "__main__":
    main()
