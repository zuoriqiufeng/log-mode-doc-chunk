# -*- coding: utf-8 -*-
"""文档分块向量化管道 — 后端 API 服务（端口 58002）

提供 REST API 用于:
- 配置管理（分块参数、向量化参数、向量数据库参数）
- 文档上传（单文件/批量）
- 文档处理（分块 + 向量化 + 存入 Qdrant）
- 任务状态查询
- 向量语义检索
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 加载 .env
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_ENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=False)
    except ImportError:
        pass

# 确保 HuggingFace 下载配置生效（load_dotenv override=False 可能跳过已存在但为空的变量）
_hf_home = os.environ.get("HF_HOME", "")
if _hf_home:
    os.environ["HF_HOME"] = _hf_home
_hf_endpoint = os.environ.get("HF_ENDPOINT", "")
if _hf_endpoint:
    os.environ["HF_ENDPOINT"] = _hf_endpoint

from flask import Flask, jsonify, request, send_from_directory

from extractors import EXTRACTOR_MAP
from pipeline import process_document
from vector_store.qdrant_config import DEFAULT_COLLECTION_NAME

# ---------------------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------------------

app = Flask(__name__)

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = set(EXTRACTOR_MAP.keys()) | {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".zip",
}

# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------

# 已上传文档: file_id -> {file_id, filename, original_name, size, ext, path, uploaded_at}
_documents: dict[str, dict[str, Any]] = {}
_documents_lock = threading.Lock()

# 处理任务: task_id -> {task_id, status, created_at, files: [...]}
_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()

# 后台线程池
_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# 文档注册表持久化（重启后 _documents 不丢失）
# ---------------------------------------------------------------------------

DOCUMENTS_JSON = os.path.join(UPLOAD_DIR, "documents.json")


def _save_documents_locked() -> None:
    """将 _documents 写入磁盘（调用方必须已持有 _documents_lock）。原子替换防截断。"""
    tmp_path = DOCUMENTS_JSON + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_documents, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DOCUMENTS_JSON)
    except OSError as e:
        print(f"[WARN] 文档注册表写入失败: {e}")


def _load_documents() -> None:
    """启动时从磁盘恢复文档注册表，过滤磁盘上已不存在的条目。"""
    if not os.path.exists(DOCUMENTS_JSON):
        return
    try:
        with open(DOCUMENTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 文档注册表读取失败: {e}")
        return
    if not isinstance(data, dict):
        return
    restored, missing = 0, 0
    for fid, doc in data.items():
        if isinstance(doc, dict) and doc.get("path") and os.path.exists(doc["path"]):
            _documents[fid] = doc
            restored += 1
        else:
            missing += 1
    if restored or missing:
        msg = f"[文档注册表] 已恢复 {restored} 个文档"
        if missing:
            msg += f"，忽略 {missing} 个磁盘缺失条目"
        print(msg)


# 任务表持久化：让「重复上一次任务」跨重启可用
TASKS_JSON = os.path.join(UPLOAD_DIR, "tasks.json")

# 历史任务保留上限（执行中的任务永不参与剪枝）
TASK_HISTORY_LIMIT = 10


def _save_tasks_locked() -> None:
    """将 _tasks 写入磁盘（调用方必须已持有 _tasks_lock）。原子替换防截断。"""
    tmp_path = TASKS_JSON + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, TASKS_JSON)
    except OSError as e:
        print(f"[WARN] 任务表写入失败: {e}")


def _prune_tasks_locked() -> None:
    """只保留最近 TASK_HISTORY_LIMIT 条任务；pending/processing 永不剪。调用方必须持锁。"""
    if len(_tasks) <= TASK_HISTORY_LIMIT:
        return
    running = {
        tid for tid, t in _tasks.items()
        if t.get("status") in ("pending", "processing")
    }
    terminal_sorted = sorted(
        (tid for tid in _tasks if tid not in running),
        key=lambda tid: _tasks[tid].get("created_at", ""),
        reverse=True,
    )
    keep_terminal = max(0, TASK_HISTORY_LIMIT - len(running))
    for tid in terminal_sorted[keep_terminal:]:
        del _tasks[tid]


def _load_tasks() -> None:
    """启动时恢复任务表；被重启打断的进行中任务标为 failed（仍可重复执行）。"""
    if not os.path.exists(TASKS_JSON):
        return
    try:
        with open(TASKS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 任务表读取失败: {e}")
        return
    if not isinstance(data, dict):
        return
    changed = False
    for tid, task in data.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") in ("pending", "processing"):
            task["status"] = "failed"
            task["error"] = task.get("error") or "服务重启中断"
            for tf in task.get("files", []):
                if tf.get("status") in ("pending", "processing"):
                    tf["status"] = "failed"
                    tf["error"] = "服务重启中断"
            changed = True
        _tasks[tid] = task
    with _tasks_lock:
        before = len(_tasks)
        _prune_tasks_locked()
        if changed or len(_tasks) != before:
            _save_tasks_locked()
    print(f"[任务表] 已恢复 {len(_tasks)} 个任务")


_load_documents()
_load_tasks()


_load_documents()


# ---------------------------------------------------------------------------
# ZIP 上传辅助
# ---------------------------------------------------------------------------

def _handle_zip_upload(file_path: str, file_id: str) -> tuple[str | None, list[str]]:
    """处理 ZIP 上传：解压并返回主 Markdown 文件路径。"""
    from utils import find_main_markdown, safe_extract_zip

    extract_dir = os.path.join(UPLOAD_DIR, f"extracted_{file_id}")
    extracted, errors = safe_extract_zip(file_path, extract_dir)

    md_path = find_main_markdown(extract_dir)
    if md_path is None:
        errors.append("ZIP 中未找到 Markdown 文件")
        return None, errors

    return md_path, errors


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------

_QDRANT_YML_PATH = os.path.join(_PROJECT_ROOT, "qdrant.yml")


def _load_config() -> dict[str, Any]:
    """从 .env 和 qdrant.yml 读取当前配置。"""
    config = {
        # 分块参数
        "chunk_size": int(os.environ.get("CHUNK_SIZE", "512")),
        "mini_chunk_size": int(os.environ.get("MINI_CHUNK_SIZE", "150")),
        "enable_large_chunks": os.environ.get("ENABLE_LARGE_CHUNKS", "true").lower() in ("true", "1", "yes"),
        "large_chunk_ratio": int(os.environ.get("LARGE_CHUNK_RATIO", "4")),
        "enable_contextual_rag": os.environ.get("ENABLE_CONTEXTUAL_RAG", "true").lower() in ("true", "1", "yes"),
        "use_llm": os.environ.get("USE_LLM", "false").lower() in ("true", "1", "yes"),
        "enable_enrichment": os.environ.get("ENABLE_ENRICHMENT", "false").lower() in ("true", "1", "yes"),
        # 图片处理参数
        "enable_image_processing": os.environ.get("ENABLE_IMAGE_PROCESSING", "false").lower() in ("true", "1", "yes"),
        "image_processor_backend": os.environ.get("IMAGE_PROCESSOR_BACKEND", "local"),
        "image_processor_model": os.environ.get("IMAGE_PROCESSOR_MODEL", "gpt-4o-mini"),
        "image_processor_api_key": "",
        "image_processor_base_url": os.environ.get("IMAGE_PROCESSOR_BASE_URL", ""),
        "ocr_languages": os.environ.get("OCR_LANGUAGES", "ch_sim,en"),
        "ocr_device": os.environ.get("OCR_DEVICE", "cpu"),
        "image_min_width": int(os.environ.get("IMAGE_MIN_WIDTH", "10") or "10"),
        "image_min_height": int(os.environ.get("IMAGE_MIN_HEIGHT", "10") or "10"),
        # 向量化参数
        "embedding_backend": os.environ.get("EMBEDDING_BACKEND", "openai"),
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        "embedding_batch_size": int(os.environ.get("EMBEDDING_BATCH_SIZE", "100") or "100"),
        "embedding_device": os.environ.get("LOCAL_EMBEDDING_DEVICE", "cpu"),
        "normalize_embeddings": os.environ.get("LOCAL_EMBEDDING_NORMALIZE", "false").lower() in ("true", "1", "yes"),
        "openai_api_key": "",
        # 日志模式库参数
        "log_pattern_collection_name": os.environ.get(
            "LOG_PATTERN_COLLECTION_NAME", "log_patterns_collection"
        ),
    }

    # API Key: 如果已设置则返回掩码
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key and api_key != "sk-your-key-here":
        config["openai_api_key"] = "sk-***"
    elif api_key == "sk-your-key-here":
        config["openai_api_key"] = ""

    image_api_key = os.environ.get("IMAGE_PROCESSOR_API_KEY", "") or api_key
    if image_api_key and image_api_key != "sk-your-key-here":
        config["image_processor_api_key"] = "sk-***"
    else:
        config["image_processor_api_key"] = ""

    # Qdrant 配置
    qdrant_config = _load_qdrant_config_file()
    config.update(qdrant_config)

    return config


def _load_qdrant_config_file() -> dict[str, Any]:
    """从 qdrant.yml 读取配置。"""
    result = {
        "qdrant_mode": "local",
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
        "qdrant_grpc_port": 6334,
        "qdrant_collection_name": DEFAULT_COLLECTION_NAME,
        "qdrant_distance": "cosine",
        "qdrant_vector_size": 1536,
        "qdrant_api_key": "",
        "qdrant_https": False,
        "qdrant_path": "./qdrant_data",
        "qdrant_upsert_batch_size": 100,
    }

    if not os.path.exists(_QDRANT_YML_PATH):
        return result

    try:
        import yaml
        with open(_QDRANT_YML_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        result["qdrant_mode"] = raw.get("mode", "local")
        result["qdrant_host"] = raw.get("host", "localhost") or "localhost"
        result["qdrant_port"] = raw.get("port", 6333) or 6333
        result["qdrant_grpc_port"] = raw.get("grpc_port", 6334) or 6334
        result["qdrant_collection_name"] = raw.get("collection_name", DEFAULT_COLLECTION_NAME)
        result["qdrant_distance"] = raw.get("distance", "cosine")
        result["qdrant_vector_size"] = raw.get("vector_size", 1536)
        result["qdrant_api_key"] = raw.get("api_key") or ""
        result["qdrant_https"] = raw.get("https", False)
        result["qdrant_path"] = raw.get("path", "./qdrant_data")
        result["qdrant_upsert_batch_size"] = raw.get("upsert_batch_size", 100)
    except Exception:
        pass

    return result


def _save_config(config: dict[str, Any]) -> None:
    """将配置写入 .env 和 qdrant.yml。"""
    # 写入 .env（分块 + 向量化参数）
    env_lines = []
    env_mapping = {
        "EMBEDDING_BACKEND": config.get("embedding_backend", "openai"),
        "EMBEDDING_MODEL": config.get("embedding_model", "text-embedding-3-small"),
        "EMBEDDING_BATCH_SIZE": str(config.get("embedding_batch_size", 100)),
        "OPENAI_MODEL": "gpt-4o-mini",
        "LOCAL_EMBEDDING_DEVICE": config.get("embedding_device", "cpu"),
        "LOCAL_EMBEDDING_NORMALIZE": str(config.get("normalize_embeddings", False)).lower(),
        "CHUNK_SIZE": str(config.get("chunk_size", 512)),
        "MINI_CHUNK_SIZE": str(config.get("mini_chunk_size", 150)),
        "ENABLE_LARGE_CHUNKS": str(config.get("enable_large_chunks", True)).lower(),
        "LARGE_CHUNK_RATIO": str(config.get("large_chunk_ratio", 4)),
        "ENABLE_CONTEXTUAL_RAG": str(config.get("enable_contextual_rag", True)).lower(),
        "USE_LLM": str(config.get("use_llm", False)).lower(),
        "ENABLE_ENRICHMENT": str(config.get("enable_enrichment", False)).lower(),
        # 图片处理参数
        "ENABLE_IMAGE_PROCESSING": str(config.get("enable_image_processing", False)).lower(),
        "IMAGE_PROCESSOR_BACKEND": config.get("image_processor_backend", "local"),
        "IMAGE_PROCESSOR_MODEL": config.get("image_processor_model", "gpt-4o-mini"),
        "IMAGE_PROCESSOR_BASE_URL": config.get("image_processor_base_url", ""),
        "OCR_LANGUAGES": config.get("ocr_languages", "ch_sim,en"),
        "OCR_DEVICE": config.get("ocr_device", "cpu"),
        "IMAGE_MIN_WIDTH": str(config.get("image_min_width", 10)),
        "IMAGE_MIN_HEIGHT": str(config.get("image_min_height", 10)),
        # 日志模式库参数
        "LOG_PATTERN_COLLECTION_NAME": config.get(
            "log_pattern_collection_name", "log_patterns_collection"
        ),
    }

    # API Keys: 只在非掩码时写入
    openai_api_key = config.get("openai_api_key", "")
    if openai_api_key and openai_api_key != "sk-***":
        env_mapping["OPENAI_API_KEY"] = openai_api_key

    image_api_key = config.get("image_processor_api_key", "")
    if image_api_key and image_api_key != "sk-***":
        env_mapping["IMAGE_PROCESSOR_API_KEY"] = image_api_key

    # 读取现有 .env 保留注释和未管理的键
    existing_lines: dict[str, str] = {}
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    existing_lines[key] = line.rstrip("\n")

    # 更新或追加
    for key, value in env_mapping.items():
        if key in existing_lines:
            existing_lines[key] = f"{key}={value}"
        else:
            existing_lines[key] = f"{key}={value}"

    # 保留注释和顺序：重新写入
    output_lines = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    output_lines.append(line.rstrip("\n"))
                elif "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_mapping:
                        output_lines.append(existing_lines[key])
                    else:
                        output_lines.append(line.rstrip("\n"))

    # 追加新增的键
    written_keys = set()
    for line in output_lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            written_keys.add(stripped.split("=", 1)[0].strip())

    for key, value in env_mapping.items():
        if key not in written_keys:
            output_lines.append(f"{key}={value}")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")

    # 更新环境变量（当前进程立即生效）
    for key, value in env_mapping.items():
        os.environ[key] = value

    # 写入 qdrant.yml
    _save_qdrant_config(config)


def _save_qdrant_config(config: dict[str, Any]) -> None:
    """将 Qdrant 配置写入 qdrant.yml。"""
    try:
        import yaml

        qdrant_data = {
            "mode": config.get("qdrant_mode", "local"),
            "path": config.get("qdrant_path", "./qdrant_data"),
            "host": config.get("qdrant_host", "localhost"),
            "port": config.get("qdrant_port", 6333),
            "grpc_port": config.get("qdrant_grpc_port", 6334),
            "api_key": config.get("qdrant_api_key") or None,
            "https": config.get("qdrant_https", False),
            "collection_name": config.get("qdrant_collection_name", DEFAULT_COLLECTION_NAME),
            "distance": config.get("qdrant_distance", "cosine"),
            "vector_size": config.get("qdrant_vector_size", 1536),
            "auto_create_collection": True,
            "upsert_batch_size": config.get("qdrant_upsert_batch_size", 100),
        }

        with open(_QDRANT_YML_PATH, "w", encoding="utf-8") as f:
            yaml.dump(qdrant_data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        print(f"[WARN] 保存 qdrant.yml 失败: {e}")


def _close_qdrant_store(store: object) -> None:
    """安全关闭 QdrantVectorStore 的底层 client。

    远程模式（QdrantRemote）需要显式关闭 httpx client；
    本地模式（QdrantLocal）无需关闭，close() 会释放内存锁。
    """
    try:
        if hasattr(store, "_client") and hasattr(store._client, "close"):
            store._client.close()
    except Exception:
        pass


def _build_qdrant_config(config: dict[str, Any]):
    """根据 web 配置构建 QdrantConfig 对象。"""
    from vector_store.qdrant_config import QdrantConfig

    mode = config.get("qdrant_mode", "local")
    return QdrantConfig(
        mode=mode,
        path=config.get("qdrant_path", "./qdrant_data") if mode == "local" else None,
        host=config.get("qdrant_host", "localhost") if mode == "remote" else None,
        port=config.get("qdrant_port", 6333) if mode == "remote" else None,
        grpc_port=config.get("qdrant_grpc_port") if mode == "remote" else None,
        api_key=config.get("qdrant_api_key") or None if mode == "remote" else None,
        https=config.get("qdrant_https", False) if mode == "remote" else False,
        collection_name=config.get("qdrant_collection_name", DEFAULT_COLLECTION_NAME),
        distance=config.get("qdrant_distance", "cosine"),
        vector_size=config.get("qdrant_vector_size", 1536),
        auto_create_collection=True,
        upsert_batch_size=config.get("qdrant_upsert_batch_size", 100),
    )


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(_load_config())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    config = request.get_json(force=True)
    if not config:
        return jsonify({"error": "请求体为空"}), 400
    _save_config(config)
    return jsonify({"status": "ok", "message": "配置已保存"})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "未找到文件，请使用 multipart/form-data 上传"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件格式: {ext}"}), 400

    file_id = str(uuid.uuid4())
    safe_name = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(file_path)
    file_size = os.path.getsize(file_path)

    errors: list[str] = []
    if ext == ".zip":
        md_path, zip_errors = _handle_zip_upload(file_path, file_id)
        errors.extend(zip_errors)
        if md_path is None:
            try:
                os.remove(file_path)
            except OSError:
                pass
            return jsonify({"error": "; ".join(errors)}), 400
        file_path = md_path

    doc_info = {
        "file_id": file_id,
        "filename": safe_name,
        "original_name": file.filename,
        "size": file_size,
        "ext": ext,
        "path": file_path,
        "uploaded_at": datetime.now().isoformat(),
    }

    with _documents_lock:
        _documents[file_id] = doc_info
        _save_documents_locked()

    return jsonify({
        "file_id": file_id,
        "filename": file.filename,
        "size": file_size,
        "type": ext.lstrip("."),
        "errors": errors if errors else None,
    })


@app.route("/api/upload/batch", methods=["POST"])
def api_upload_batch():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "未找到文件"}), 400

    results = []
    errors = []

    for file in files:
        if not file.filename:
            errors.append({"filename": "", "error": "文件名为空"})
            continue

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append({"filename": file.filename, "error": f"不支持的格式: {ext}"})
            continue

        file_id = str(uuid.uuid4())
        safe_name = f"{file_id}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        file.save(file_path)
        file_size = os.path.getsize(file_path)

        file_errors: list[str] = []
        if ext == ".zip":
            md_path, zip_errors = _handle_zip_upload(file_path, file_id)
            file_errors.extend(zip_errors)
            if md_path is None:
                errors.append({
                    "filename": file.filename,
                    "error": "; ".join(file_errors),
                })
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                continue
            file_path = md_path

        doc_info = {
            "file_id": file_id,
            "filename": safe_name,
            "original_name": file.filename,
            "size": file_size,
            "ext": ext,
            "path": file_path,
            "uploaded_at": datetime.now().isoformat(),
        }

        with _documents_lock:
            _documents[file_id] = doc_info
            _save_documents_locked()

        results.append({
            "file_id": file_id,
            "filename": file.filename,
            "size": file_size,
            "type": ext.lstrip("."),
            "errors": file_errors if file_errors else None,
        })

    return jsonify({"files": results, "errors": errors})


@app.route("/api/documents", methods=["GET"])
def api_list_documents():
    with _documents_lock:
        docs = [
            {
                "file_id": d["file_id"],
                "filename": d["original_name"],
                "size": d["size"],
                "type": d["ext"].lstrip("."),
                "uploaded_at": d["uploaded_at"],
            }
            for d in _documents.values()
        ]
    return jsonify({"documents": docs})


@app.route("/api/documents/<file_id>", methods=["DELETE"])
def api_delete_document(file_id: str):
    with _documents_lock:
        doc = _documents.pop(file_id, None)
        if doc:
            _save_documents_locked()

    if doc:
        if doc.get("ext") == ".zip":
            # zip 文档的 path 指向解压出的 md，连同解压目录与原 zip 一并清理
            shutil.rmtree(os.path.join(UPLOAD_DIR, f"extracted_{file_id}"), ignore_errors=True)
            zip_path = os.path.join(UPLOAD_DIR, f"{file_id}.zip")
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
        else:
            try:
                os.remove(doc["path"])
            except OSError:
                pass
        return jsonify({"status": "ok"})
    return jsonify({"error": "文件不存在"}), 404


def _create_and_submit_task(
    valid_files: list[dict],
    enable_embedding: bool,
    enable_vector_store: bool,
) -> str:
    """创建任务并提交后台处理，返回 task_id（/api/process 与 /api/tasks/repeat 共用）。"""
    task_id = str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "enable_embedding": enable_embedding,
        "enable_vector_store": enable_vector_store,
        "files": [
            {
                "file_id": f["file_id"],
                "filename": f["original_name"],
                "status": "pending",
                "chunk_count": 0,
                "mini_chunk_count": 0,
                "large_chunk_count": 0,
                "error": None,
            }
            for f in valid_files
        ],
    }

    with _tasks_lock:
        _tasks[task_id] = task
        # 同批合并：同一批文件的历史终态任务被新记录顶替，恒只留一张卡片。
        # 执行中的任务绝不能删（worker 持有 task_id 引用，删了会 KeyError）。
        new_key = tuple(sorted(f["file_id"] for f in task["files"]))
        for tid in list(_tasks.keys()):
            if tid == task_id:
                continue
            old = _tasks[tid]
            if old.get("status") in ("pending", "processing"):
                continue
            old_key = tuple(sorted(f.get("file_id", "") for f in old.get("files", [])))
            if old_key == new_key:
                del _tasks[tid]
        _prune_tasks_locked()
        _save_tasks_locked()

    # 读取当前配置（请求时刻快照）
    config = _load_config()

    # 提交后台处理
    _executor.submit(
        _process_files_background,
        task_id, valid_files, config,
        enable_embedding, enable_vector_store,
    )
    return task_id


@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.get_json(force=True) or {}
    file_ids = data.get("file_ids", [])
    enable_embedding = data.get("enable_embedding", True)
    enable_vector_store = data.get("enable_vector_store", True)

    if not file_ids:
        return jsonify({"error": "未指定要处理的文件"}), 400

    # 验证 file_ids（浅拷贝快照，缩窄与 DELETE 的竞态窗口）
    valid_files = []
    with _documents_lock:
        for fid in file_ids:
            if fid in _documents:
                valid_files.append(dict(_documents[fid]))

    if not valid_files:
        return jsonify({"error": "未找到有效的文件"}), 400

    task_id = _create_and_submit_task(valid_files, enable_embedding, enable_vector_store)

    return jsonify({
        "task_id": task_id,
        "file_count": len(valid_files),
        "status": "pending",
    })


def _process_single_file(
    task_id: str,
    file_info: dict,
    config: dict[str, Any],
    enable_embedding: bool,
    enable_vector_store: bool,
    qdrant_config: Any | None,
) -> None:
    """处理单个文件并更新其任务状态（文件级并发的 worker，内部自行兜底异常）。"""
    file_id = file_info["file_id"]
    file_path = file_info["path"]

    # 更新文件状态
    with _tasks_lock:
        for f in _tasks[task_id]["files"]:
            if f["file_id"] == file_id:
                f["status"] = "processing"
                break
        _save_tasks_locked()

    try:
        output_dir = os.path.join(UPLOAD_DIR, f"output_{file_id}")

        # 分块 + 嵌入（不写 Qdrant，由后面单独处理）
        document, chunks, images = process_document(
            file_path=file_path,
            output_dir=output_dir,
            chunk_token_limit=config.get("chunk_size", 512),
            mini_chunk_size=config.get("mini_chunk_size", 150),
            enable_large_chunks=config.get("enable_large_chunks", True),
            large_chunk_ratio=config.get("large_chunk_ratio", 4),
            enable_contextual_rag=config.get("enable_contextual_rag", True),
            use_llm_for_contextual_rag=config.get("use_llm", False),
            enable_embedding=enable_embedding,
            embedding_backend=config.get("embedding_backend", "openai"),
            embedding_model=config.get("embedding_model"),
            embedding_device=config.get("embedding_device", "cpu"),
            embedding_batch_size=config.get("embedding_batch_size"),
            normalize_embeddings=config.get("normalize_embeddings", False),
            enable_vector_store=False,  # 不在 pipeline 中写入 Qdrant
            enable_enrichment=config.get("enable_enrichment", False),
            enable_image_processing=config.get("enable_image_processing", False),
            image_processor_backend=config.get("image_processor_backend", "local"),
            image_processor_model=config.get("image_processor_model", "gpt-4o-mini"),
            image_processor_base_url=config.get("image_processor_base_url", ""),
        )

        # 单独写入 Qdrant（每个文件独立 store，避免线程间共享 client）。
        # 写入失败不再静默吞掉：异常向上传播 → 文件标 failed（防"完成但没进库"）。
        if qdrant_config and enable_embedding:
            file_store = None
            try:
                from vector_store.qdrant_store import QdrantVectorStore
                file_store = QdrantVectorStore(config=qdrant_config)

                from models import IndexChunk
                index_chunks = [c for c in chunks if isinstance(c, IndexChunk)]
                if index_chunks:
                    file_store.upsert_chunks(index_chunks)
                    print(f"    Qdrant 写入完成: {len(index_chunks)} 个 chunk")
            finally:
                if file_store:
                    _close_qdrant_store(file_store)

        # 统计
        normal_chunks = [c for c in chunks if not c.is_large_chunk]
        large_chunks = [c for c in chunks if c.is_large_chunk]
        mini_count = sum(len(c.mini_chunk_texts or []) for c in normal_chunks)

        with _tasks_lock:
            for f in _tasks[task_id]["files"]:
                if f["file_id"] == file_id:
                    f["status"] = "completed"
                    f["chunk_count"] = len(normal_chunks)
                    f["mini_chunk_count"] = mini_count
                    f["large_chunk_count"] = len(large_chunks)
                    break
            _save_tasks_locked()

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[ERROR] 处理文件 {file_info.get('original_name', '')} 失败:\n{tb}")
        with _tasks_lock:
            for f in _tasks[task_id]["files"]:
                if f["file_id"] == file_id:
                    f["status"] = "failed"
                    f["error"] = str(e)
                    break
            _save_tasks_locked()


def _process_files_background(
    task_id: str,
    files: list[dict],
    config: dict[str, Any],
    enable_embedding: bool,
    enable_vector_store: bool,
) -> None:
    """后台线程处理文件：文件级并发；任务终态在池关闭后由外层线程恰好一次收口。"""
    with _tasks_lock:
        _tasks[task_id]["status"] = "processing"
        _save_tasks_locked()

    # 在后台线程中为每个文件创建独立的 Qdrant store
    # 本地模式 Qdrant 使用 SQLite，不支持跨线程共享 client
    qdrant_config = None
    if enable_vector_store and enable_embedding:
        try:
            qdrant_config = _build_qdrant_config(config)
            # 禁用 gRPC，使用纯 HTTP 以避免线程安全问题
            qdrant_config.grpc_port = None
        except Exception as e:
            print(f"[WARN] Qdrant 配置构建失败: {e}")

    file_concurrency = max(1, int(os.environ.get("FILE_CONCURRENCY", "3")))
    worker_count = max(1, min(file_concurrency, len(files) or 1))

    # 文件级并发：单文件失败已在 worker 内部捕获并标 failed，不影响其他文件
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(
                _process_single_file,
                task_id, f, config,
                enable_embedding, enable_vector_store, qdrant_config,
            )
            for f in files
        ]
        for fut in as_completed(futures):
            exc = fut.exception()
            if exc is not None:  # worker 内部已兜底，此处防编程错误
                print(f"[ERROR] 文件 worker 异常: {exc}")

    # 池已关闭（所有文件 worker 结束）→ 外层线程恰好一次收口任务终态
    with _tasks_lock:
        task = _tasks[task_id]
        all_done = all(f["status"] in ("completed", "failed") for f in task["files"])
        if all_done:
            any_failed = any(f["status"] == "failed" for f in task["files"])
            task["status"] = "completed" if not any_failed else "partial"
        _save_tasks_locked()


def _snapshot_task(task: dict) -> dict:
    """锁内构造任务快照（含 files），避免与后台并发写产生撕裂视图。"""
    return {
        **task,
        "files": [dict(f) for f in task.get("files", [])],
    }


@app.route("/api/tasks", methods=["GET"])
def api_list_tasks():
    with _tasks_lock:
        tasks = [_snapshot_task(t) for t in _tasks.values()]
    # 按创建时间倒序
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return jsonify({"tasks": tasks})


@app.route("/api/tasks/<task_id>", methods=["GET"])
def api_get_task(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
        snapshot = _snapshot_task(task) if task else None
    if not snapshot:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(snapshot)


@app.route("/api/tasks/repeat", methods=["POST"])
def api_repeat_last_task():
    """重复执行最近一次任务：文件清单取上次任务，已删除的文件自动跳过。"""
    with _tasks_lock:
        if not _tasks:
            return jsonify({"error": "没有可重复的任务"}), 400
        latest = max(_tasks.values(), key=lambda t: t.get("created_at", ""))
        latest = _snapshot_task(latest)
        enable_embedding = latest.get("enable_embedding", True)
        enable_vector_store = latest.get("enable_vector_store", True)

    if latest.get("status") in ("pending", "processing"):
        return jsonify({"error": "上一个任务尚在执行中"}), 400

    wanted = [f.get("file_id") for f in latest.get("files", []) if f.get("file_id")]
    valid_files: list[dict] = []
    skipped = 0
    with _documents_lock:
        for fid in wanted:
            doc = _documents.get(fid)
            if doc:
                valid_files.append(dict(doc))
            else:
                skipped += 1

    if not valid_files:
        return jsonify({"error": "上一次任务的文件均已不存在"}), 400

    task_id = _create_and_submit_task(valid_files, enable_embedding, enable_vector_store)
    return jsonify({
        "task_id": task_id,
        "file_count": len(valid_files),
        "skipped": skipped,
        "status": "pending",
    })


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def api_delete_task(task_id: str):
    """删除历史任务（执行中的不允许删）。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        if task.get("status") in ("pending", "processing"):
            return jsonify({"error": "任务执行中，无法删除"}), 400
        _tasks.pop(task_id, None)
        _save_tasks_locked()
    return jsonify({"status": "ok"})


@app.route("/api/query", methods=["POST"])
def api_query():
    data = request.get_json(force=True) or {}
    query_text = data.get("query", "").strip()
    top_k = data.get("top_k", 5)
    filters = data.get("filters")

    if not query_text:
        return jsonify({"error": "查询文本不能为空"}), 400

    try:
        config = _load_config()

        # 构建嵌入模型
        from embedding import create_embedding_model
        model = create_embedding_model(
            backend=config.get("embedding_backend", "local"),
            model_name=config.get("embedding_model"),
            device=config.get("embedding_device", "cpu"),
            normalize_embeddings=config.get("normalize_embeddings", False),
        )

        # 构建向量存储（禁用 gRPC 避免线程安全问题）
        from vector_store.qdrant_store import QdrantVectorStore
        qconf = _build_qdrant_config(config)
        qconf.grpc_port = None
        store = QdrantVectorStore(config=qconf)

        try:
            if store.get_chunk_count() == 0:
                return jsonify({"results": [], "message": "向量数据库为空"})

            # 搜索（每次查询创建独立的 store 实例，避免线程间共享 client）
            from vector_store.searcher import Searcher
            searcher = Searcher(vector_store=store, embedding_model=model)
            results = searcher.search(query=query_text, top_k=top_k, filters=filters)

            return jsonify({
                "results": [
                    {
                        "document_id": r.document_id,
                        "chunk_id": r.chunk_id,
                        "content": r.content[:2000],
                        "score": round(r.score, 4),
                        "title": r.title,
                        "section_type": r.section_type,
                        "is_large_chunk": r.is_large_chunk,
                        "chunk_level": r.chunk_level,
                        "source_chunk_ids": r.source_chunk_ids,
                        "doc_summary": r.doc_summary[:300] if r.doc_summary else "",
                        "chunk_context": r.chunk_context[:300] if r.chunk_context else "",
                    }
                    for r in results
                ]
            })
        finally:
            # 确保 Qdrant client 正确关闭
            _close_qdrant_store(store)

    except Exception as e:
        return jsonify({"error": f"查询失败: {e}"}), 500


@app.route("/api/search", methods=["POST"])
def api_search():
    """i2Agent RAG 集成专用搜索端点。

    与 /api/query 不同，此端点返回 i2Agent RAGResult 兼容格式：
    { "results": [{ "content": "...", "score": 0.95, "metadata": {} }] }
    """
    data = request.get_json(force=True) or {}
    query_text = data.get("query", "").strip()
    top_k = int(data.get("top_k", 3))

    if not query_text:
        return jsonify({"error": "查询文本不能为空"}), 400

    try:
        config = _load_config()

        # 构建嵌入模型
        from embedding import create_embedding_model
        model = create_embedding_model(
            backend=config.get("embedding_backend", "local"),
            model_name=config.get("embedding_model"),
            device=config.get("embedding_device", "cpu"),
            normalize_embeddings=config.get("normalize_embeddings", False),
        )

        # 构建向量存储（禁用 gRPC 避免线程安全问题）
        from vector_store.qdrant_store import QdrantVectorStore
        qconf = _build_qdrant_config(config)
        qconf.grpc_port = None
        store = QdrantVectorStore(config=qconf)

        try:
            from vector_store.searcher import Searcher
            searcher = Searcher(vector_store=store, embedding_model=model)
            results = searcher.search(query=query_text, top_k=top_k)

            return jsonify({
                "results": [
                    {
                        "content": r.content[:2000],
                        "score": round(r.score, 4),
                        "metadata": {
                            "document_id": r.document_id,
                            "chunk_id": r.chunk_id,
                            "title": r.title,
                            "section_type": r.section_type,
                            "is_large_chunk": r.is_large_chunk,
                        },
                    }
                    for r in results
                ]
            })
        finally:
            _close_qdrant_store(store)

    except Exception as e:
        return jsonify({"error": f"查询失败: {e}"}), 500


@app.route("/api/index", methods=["POST"])
def api_index():
    """增量索引 API：接收单条文档，进行向量化后写入 Qdrant。

    用于 i2Agent RAG 集成：新模板/分析结果实时写入向量库。

    请求体:
    {
        "content": "文档内容文本",
        "metadata": {"key": "value"},
        "document_id": "可选，用于幂等写入"
    }
    """
    data = request.get_json(force=True) or {}
    content = data.get("content", "").strip()
    metadata = data.get("metadata", {})
    document_id = data.get("document_id", "")

    if not content:
        return jsonify({"error": "content 不能为空"}), 400

    try:
        config = _load_config()

        # 构建嵌入模型
        from embedding import create_embedding_model
        model = create_embedding_model(
            backend=config.get("embedding_backend", "local"),
            model_name=config.get("embedding_model"),
            device=config.get("embedding_device", "cpu"),
            normalize_embeddings=config.get("normalize_embeddings", False),
        )

        # 生成 embedding
        embeddings = model.encode([content])
        if not embeddings or len(embeddings) == 0:
            return jsonify({"error": "向量化失败"}), 500

        # 构建 Qdrant store
        from vector_store.qdrant_store import QdrantVectorStore
        qconf = _build_qdrant_config(config)
        qconf.grpc_port = None
        store = QdrantVectorStore(config=qconf)

        try:
            # 生成确定性 point ID（幂等写入）
            if not document_id:
                document_id = str(uuid.uuid4())
            chunk_id = "0"
            point_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_{chunk_id}")

            # 构建 IndexChunk
            from models import Document, IndexChunk, ChunkEmbedding, SectionType
            doc = Document(
                id=document_id,
                semantic_identifier=metadata.get("title", document_id),
                sections=[],
                metadata=metadata,
            )
            section_type_str = metadata.get("section_type", "text")
            try:
                section_type = SectionType(section_type_str)
            except ValueError:
                section_type = SectionType.TEXT

            index_chunk = IndexChunk(
                source_document=doc,
                chunk_id=int(chunk_id),
                content=content,
                blurb=content[:150],
                section_type=section_type,
                title_prefix=metadata.get("title", ""),
                mini_chunk_texts=[],
                large_chunk_reference_ids=[],
                doc_summary="",
                chunk_context="",
                section_continuation=False,
                embeddings=ChunkEmbedding(
                    full_embedding=embeddings[0],
                    mini_chunk_embeddings=[],
                ),
            )

            store.upsert_chunks([index_chunk])

            return jsonify({
                "status": "indexed",
                "document_id": document_id,
                "chunk_id": chunk_id,
                "point_id": str(point_id),
            })
        finally:
            _close_qdrant_store(store)

    except Exception as e:
        return jsonify({"error": f"索引失败: {e}"}), 500


# ---------------------------------------------------------------------------
# 日志模式库导入
# ---------------------------------------------------------------------------

_LOG_PATTERN_ALLOWED_EXT = {".json", ".yaml", ".yml", ".csv", ".tsv", ".xlsx", ".xls"}


@app.route("/api/log_patterns/import", methods=["POST"])
def api_log_patterns_import():
    """导入日志模式文件（JSON/YAML/CSV/Excel）。

    multipart/form-data:
        file: 日志模式文件
        collection_name: 可选，目标 collection（默认配置中的 log_pattern_collection_name）
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "未提供文件"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _LOG_PATTERN_ALLOWED_EXT:
        return jsonify({"error": f"不支持的格式 {ext}，支持: {sorted(_LOG_PATTERN_ALLOWED_EXT)}"}), 400

    collection_name = request.form.get("collection_name") or None

    # 保存到临时文件后复用 importer
    import tempfile
    suffix = ext
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=suffix, delete=False
        ) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        from log_patterns.importer import import_log_patterns

        result = import_log_patterns(
            file_path=tmp_path,
            collection_name=collection_name,
        )
        status_code = 200 if result.get("invalid_patterns", 0) == 0 else 207
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"error": f"日志模式导入失败: {e}"}), 500
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.route("/api/log_patterns/import_json", methods=["POST"])
def api_log_patterns_import_json():
    """从内联 JSON 导入日志模式。

    请求体:
    {
        "patterns": [{ "pattern_id": "LP-0001", ... }],
        "collection_name": "可选"
    }
    """
    data = request.get_json(force=True) or {}
    patterns = data.get("patterns")
    if not patterns or not isinstance(patterns, list):
        return jsonify({"error": "patterns 必须是非空数组"}), 400

    collection_name = data.get("collection_name") or None

    try:
        from log_patterns.importer import import_log_patterns_from_data

        result = import_log_patterns_from_data(
            patterns_data=patterns,
            collection_name=collection_name,
        )
        status_code = 200 if result.get("invalid_patterns", 0) == 0 else 207
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"error": f"日志模式导入失败: {e}"}), 500


@app.route("/api/log_patterns/collections", methods=["GET"])
def api_log_patterns_collections():
    """返回日志模式目标 collection 配置与现有 Qdrant 集合列表。"""
    config = _load_config()
    target = config.get("log_pattern_collection_name", "log_patterns_collection")

    existing: list[str] = []
    try:
        qconf = _build_qdrant_config(config)
        qconf.grpc_port = None
        from vector_store.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(config=qconf)
        try:
            existing = [c.name for c in store._client.get_collections().collections]
        finally:
            _close_qdrant_store(store)
    except Exception as e:
        return jsonify({
            "log_pattern_collection_name": target,
            "existing_collections": existing,
            "error": f"无法连接 Qdrant: {e}",
        })

    return jsonify({
        "log_pattern_collection_name": target,
        "existing_collections": existing,
    })


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("文档分块向量化管道 — 后端 API 服务")
    print(f"监听端口: 58002")
    print(f"项目根目录: {_PROJECT_ROOT}")
    print(f"上传目录: {UPLOAD_DIR}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=58002, debug=False)
