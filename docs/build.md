# chunk 构建与运行

## 环境要求

- Python 3.9+（当前验证环境为 3.13）
- 建议使用虚拟环境

## 安装依赖

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt      # 全部基础依赖，见文件内分组注释
```

## 按功能可选依赖

```bash
# 本地嵌入后端（EMBEDDING_BACKEND=local）
pip install sentence-transformers

# 本地图片 OCR 后端（IMAGE_PROCESSOR_BACKEND=local）
pip install -r requirements-image.txt
```

## 配置

```bash
cp .env.example .env    # 再按需修改；.env 已被 .gitignore 排除
```

## CLI 使用

```bash
# 基础分块（无嵌入）
python multi_doc_processor.py document.md

# 指定输出目录
python multi_doc_processor.py document.md output_dir

# OpenAI 嵌入
python multi_doc_processor.py doc.md out --embed

# 本地嵌入
python multi_doc_processor.py doc.md out --embed --embedding-backend local --embedding-model all-MiniLM-L6-v2

# LLM-based Contextual RAG（需要 OPENAI_API_KEY）
python multi_doc_processor.py doc.md out --embed --use-llm

# 写入 Qdrant（需要 --embed）
python multi_doc_processor.py doc.md out --embed --enable-vector-store

# BGE 预富化
python multi_doc_processor.py doc.md out --embed --enrich

# 启用图片处理（本地 EasyOCR）
python multi_doc_processor.py doc.md out --embed --enable-image-processing --image-processor-backend local

# 启用图片处理（远程 Vision，如 OpenAI / 兼容接口）
python multi_doc_processor.py doc.md out --embed --enable-image-processing --image-processor-backend remote --image-processor-model gpt-4o-mini

# 写入 Qdrant 并启用图片处理
python multi_doc_processor.py doc.md out --embed --enable-vector-store --enable-image-processing --image-processor-backend remote
```

## 日志模式库导入 CLI

```bash
# 直接导入（默认写入 log_patterns_collection）
python import_log_patterns.py patterns.json

# 指定集合与嵌入模型
python import_log_patterns.py patterns.xlsx \
  --collection log_patterns_collection \
  --embedding-backend local \
  --embedding-model BAAI/bge-large-zh-v1.5 \
  --embedding-device cpu

# 只解析分块不嵌入入库（输出 chunks.json 供检查）
python import_log_patterns.py patterns.csv --dry-run --output-dir /tmp/lp_test
```

支持格式：`.json` / `.yaml` / `.yml` / `.csv` / `.tsv` / `.xlsx` / `.xls`。
字段别名自动归一化（如 `patternId` / `pattern_id` / `id` 均可）；CSV/Excel 中多值字段用 `;` 或 `|` 分隔。
相同 `pattern_id` 重复导入会覆盖旧数据（幂等）。

## 查询 CLI

```bash
python query.py "search text" --top-k 5
python query.py "query" --filter document_id=path/to/file
```

## Web 服务

```bash
# 同时启动前后端
python web/start.py

# 单独启动
python web/app.py          # 后端 58002
python web/frontend.py     # 前端 58001
```

## 验证

当前没有测试套件或 linter，验证方式：

```bash
# 1. 分块链路（不依赖外部服务）
python multi_doc_processor.py word/sample.md /tmp/chunk_out

# 2. Web 服务健康检查
./web/ctl.sh start && curl -sf http://localhost:58002/api/health
```

`tests/` 目录目前只有空占位，尚无自动化用例。
