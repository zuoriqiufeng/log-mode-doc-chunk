"""Qdrant 配置测试：默认 collection 常量、yml 解析、本地/远程模式差异。"""

from __future__ import annotations

import os
import re

import pytest

from vector_store.qdrant_config import (
    DEFAULT_COLLECTION_NAME,
    QdrantConfig,
    load_qdrant_config,
)

VALID_DISTANCES = {"cosine", "euclidean", "dot"}


class TestDefaultCollectionName:
    def test_constant_is_not_the_legacy_project_name(self):
        # 旧项目名 test_doc 已清理，默认值应当是中性的 chunk_collection
        assert DEFAULT_COLLECTION_NAME == "chunk_collection"

    def test_dataclass_default_uses_constant(self):
        assert QdrantConfig(mode="local").collection_name == DEFAULT_COLLECTION_NAME

    def test_fallback_uses_constant(self, tmp_path):
        """配置文件缺失时的兜底值必须与常量一致，否则会在两处漂移。"""
        config = load_qdrant_config(str(tmp_path / "missing.yml"))
        assert config.collection_name == DEFAULT_COLLECTION_NAME


class TestLoadQdrantConfig:
    def test_missing_file_falls_back_to_local_mode(self, tmp_path):
        config = load_qdrant_config(str(tmp_path / "nope.yml"))

        assert config.mode == "local"
        assert config.path == "./qdrant_data"
        assert config.host is None
        assert config.distance == "cosine"
        assert config.vector_size == 1536
        assert config.auto_create_collection is True

    def test_local_mode_yml(self, tmp_path):
        path = tmp_path / "qdrant.yml"
        path.write_text(
            "mode: local\n"
            "path: ./my_data\n"
            "collection_name: my_chunks\n"
            "distance: dot\n"
            "vector_size: 1024\n"
            "auto_create_collection: false\n"
            "upsert_batch_size: 50\n",
            encoding="utf-8",
        )
        config = load_qdrant_config(str(path))

        assert config.mode == "local"
        assert config.path == "./my_data"
        assert config.collection_name == "my_chunks"
        assert config.distance == "dot"
        assert config.vector_size == 1024
        assert config.auto_create_collection is False
        assert config.upsert_batch_size == 50
        # local 模式下远程字段必须为空，避免误用
        assert config.host is None
        assert config.port is None
        assert config.api_key is None
        assert config.https is False

    def test_remote_mode_yml(self, tmp_path):
        path = tmp_path / "qdrant.yml"
        path.write_text(
            "mode: remote\n"
            "host: qdrant.internal\n"
            "port: 6333\n"
            "grpc_port: 6334\n"
            "https: true\n"
            "api_key: secret\n"
            "vector_size: 1024\n",
            encoding="utf-8",
        )
        config = load_qdrant_config(str(path))

        assert config.mode == "remote"
        assert config.host == "qdrant.internal"
        assert config.port == 6333
        assert config.grpc_port == 6334
        assert config.https is True
        assert config.api_key == "secret"
        # remote 模式下 path 必须为空
        assert config.path is None

    def test_empty_yml_uses_defaults(self, tmp_path):
        path = tmp_path / "qdrant.yml"
        path.write_text("", encoding="utf-8")
        config = load_qdrant_config(str(path))

        assert config.mode == "local"
        assert config.collection_name == DEFAULT_COLLECTION_NAME
        assert config.vector_size == 1536

    def test_project_qdrant_yml_is_loadable_and_sane(self, project_root):
        """仓库自带的 qdrant.yml 必须能被解析，且字段取值合法。"""
        path = os.path.join(project_root, "qdrant.yml")
        if not os.path.exists(path):
            pytest.skip("仓库内没有 qdrant.yml")

        config = load_qdrant_config(path)

        assert config.mode in {"local", "remote"}
        assert config.collection_name
        assert config.distance in VALID_DISTANCES
        assert config.vector_size > 0
        assert config.upsert_batch_size > 0


class TestNoStaleProjectName:
    """回归守卫：旧项目名不应再出现在源码的默认值里。"""

    SKIP_DIRS = {
        "venv",
        ".venv",
        "__pycache__",
        ".git",
        "HuggingFace",
        "qdrant_data",
        "uploads",
        ".image_cache",
        "resume_output",
        ".zcode",
        "node_modules",
    }

    # 用「前后不能是字母数字」界定，避免误伤 test_document_id 这类标识符
    LEGACY_PATTERN = re.compile(r"(?<![A-Za-z0-9])test_doc(?![A-Za-z0-9])")

    def test_python_sources_do_not_use_legacy_collection_name(self, project_root):
        offenders: list[str] = []
        self_path = os.path.abspath(__file__)

        for dirpath, dirnames, filenames in os.walk(project_root):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                # 本文件需要写出旧名才能做断言，跳过自身
                if os.path.abspath(full) == self_path:
                    continue
                try:
                    with open(full, "r", encoding="utf-8") as handle:
                        for lineno, line in enumerate(handle, start=1):
                            if self.LEGACY_PATTERN.search(line):
                                rel = os.path.relpath(full, project_root)
                                offenders.append(f"{rel}:{lineno}")
                except (OSError, UnicodeDecodeError):
                    continue

        assert not offenders, f"仍在源码中引用旧项目名: {offenders}"
