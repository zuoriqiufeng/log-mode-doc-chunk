# -*- coding: utf-8 -*-
"""文档分块向量化平台 — 前端服务器（端口 58001）

提供静态文件服务，并将 /api/* 请求代理到后端 API 服务器（端口 58002）。
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from flask import Flask, Response, request, send_from_directory

app = Flask(__name__, static_folder="static")

BACKEND_URL = "http://localhost:58002"

# 支持的文档扩展名（用于前端过滤显示）
SUPPORTED_EXTENSIONS = [
    ".pdf", ".txt", ".doc", ".docx",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".md", ".markdown", ".html", ".htm",
    ".xlsx", ".xls",
    ".csv", ".tsv", ".json", ".xml", ".log",
    ".conf", ".cfg", ".ini", ".yml", ".yaml", ".sql",
]


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_api(path):
    """将 /api/* 请求代理到后端 API 服务器。"""
    import requests as req

    url = f"{BACKEND_URL}/api/{path}"

    # 转发请求头（排除 Host）
    headers = {k: v for k, v in request.headers if k.lower() != "host"}
    headers["Content-Type"] = request.content_type or "application/json"

    try:
        resp = req.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            params=request.args,
            timeout=300,
        )
        return Response(
            resp.content,
            status=resp.status_code,
            headers=dict(resp.headers),
        )
    except req.ConnectionError:
        return Response(
            '{"error": "后端服务未启动，请检查端口 58002"}',
            status=502,
            content_type="application/json",
        )
    except req.Timeout:
        return Response(
            '{"error": "后端服务响应超时"}',
            status=504,
            content_type="application/json",
        )


if __name__ == "__main__":
    print("=" * 60)
    print("文档分块向量化平台 — 前端服务器")
    print(f"监听端口: 58001")
    print(f"后端地址: {BACKEND_URL}")
    print(f"访问地址: http://localhost:58001")
    print("=" * 60)
    app.run(host="0.0.0.0", port=58001, debug=False)
