# chunk

多格式文档处理与向量化管道 — 把任意格式的文档切成带语义的块（chunk），生成向量并存入 Qdrant，为 RAG 检索服务。

设计参考 [Onyx](https://github.com/onyx-dot-app/onyx)（原 Danswer）的文档索引流水线，是一个可独立运行的简化实现，目前为 i2Agent 的日志分析引擎提供 RAG 数据底座。

## 核心能力

- **多格式提取**：PDF、Word（`.docx`/`.doc`）、Excel（`.xlsx`/`.xls`）、Markdown、HTML、纯文本、图片、CSV/TSV、JSON、XML、日志文件。
- **三层块结构**：标准 chunk + mini-chunk（细粒度召回）+ large chunk（多块合并，供上下文聚合）。
- **图片处理双后端**：本地 EasyOCR 或远程 Vision 模型，识别结果作为独立 Section 注入，带结果缓存。
- **富化与 Contextual RAG**：符号/数据类型标注（BGE 预富化）、`doc_summary` + `chunk_context` 上下文增强（规则或 LLM 两种模式）。
- **可替换的嵌入层**：OpenAI API 或本地 sentence-transformers 模型，通过工厂函数按配置创建。
- **Qdrant 落库与检索**：mini-chunk 检索 + large chunk 聚合 + 关键词兜底（hybrid search）。
- **日志模式库**：独立导入链路，把「日志特征 → 根因 → 处置」结构化知识（JSON/YAML/CSV/Excel）导入独立 collection。
- **Web 界面**：配置管理、拖拽/ZIP 上传、任务轮询、语义检索、日志模式导入。

## 处理流程

```
文档文件
  └─► 提取（文本 + 元数据 + 图片）
        └─► 图片处理（OCR / Vision，可选）
              └─► 富化（符号与数据类型标注，可选）
                    └─► 分块（标准 chunk + mini-chunk + 图片块 + 表格块）
                          └─► 大 chunk 合并（multipass）
                                └─► Contextual RAG（doc_summary + chunk_context）
                                      └─► 向量嵌入（OpenAI / 本地模型）
                                            └─► Qdrant / 本地文件
```

数据单向流动，阶段之间以 `DocAwareChunk` 列表传递，每个阶段就地补充字段、不覆盖上游结果。

## 目录结构

```
chunk/
├── models.py                 # 数据模型：Section / Document / DocAwareChunk / IndexChunk
├── pipeline.py               # 主流程编排（各阶段的调用顺序）
├── multi_doc_processor.py    # CLI 入口
├── query.py                  # 向量检索 CLI
├── contextual_rag.py         # Contextual RAG 上下文增强
├── enrichment.py             # BGE 预富化（关键词 / 数据类型）
├── utils.py                  # 保存结果、打印、表格检测等工具
├── import_log_patterns.py    # 日志模式导入便捷入口
├── qdrant.yml                # Qdrant 连接与 collection 配置
│
├── extractors/               # 文档提取器，按扩展名经 EXTRACTOR_MAP 分发
├── chunking/                 # 分块：文本 / 图片 / 表格 / 大 chunk / 日志
├── embedding/                # 嵌入后端：OpenAI / 本地模型 + 工厂
├── image_processing/         # 图片处理：EasyOCR / 远程 Vision + 缓存
├── vector_store/             # Qdrant 读写与检索
├── log_patterns/             # 日志模式解析、分块、导入
│
├── web/                      # Web 界面：后端 API + 前端 SPA
├── docs/                     # 文档（见下方索引）
├── word/                     # 样例文档（sample.*；大体积真实文档不入库）
└── tests/                    # 预留测试目录（当前为空）
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 可选：本地嵌入后端
pip install sentence-transformers
# 可选：本地图片 OCR 后端
pip install -r requirements-image.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env：至少填写嵌入后端与对应密钥
```

`qdrant.yml` 中的 `vector_size` 必须与嵌入模型维度一致（如 `BAAI/bge-large-zh-v1.5` 为 1024，`text-embedding-3-small` 为 1536）。

### 3. 运行

```bash
# 分块（不嵌入）
python multi_doc_processor.py word/sample.md

# 分块 + 本地嵌入 + 写入 Qdrant
python multi_doc_processor.py word/sample.md out \
  --embed --embedding-backend local --embedding-model BAAI/bge-large-zh-v1.5 \
  --enable-vector-store

# 启用图片处理（远程 Vision）
python multi_doc_processor.py doc.pdf out --embed \
  --enable-image-processing --image-processor-backend remote

# 检索
python query.py "如何配置数据库节点" --top-k 5

# 日志模式入库
python import_log_patterns.py patterns.xlsx --collection log_patterns_collection
```

### 4. Web 界面

```bash
./web/ctl.sh start      # 后端 :58002，前端 :58001
./web/ctl.sh status
./web/ctl.sh stop
```

也可单独启动：`python web/app.py`（单进程模式，同时提供 API 与静态页面）。

## 配置

| 文件 | 作用 |
|------|------|
| `.env` | 运行配置：嵌入后端、图片处理后端、分块参数、并发度（模板见 `.env.example`） |
| `qdrant.yml` | Qdrant 连接地址、`collection_name`、`vector_size`、距离度量、批量大小 |

优先级：CLI 参数 > `.env` 环境变量 > 代码内默认值。

> **`.env` 含真实 API Key，已在 `.gitignore` 中排除，切勿提交。**

## 文档索引

工程规范（`docs/`）：

| 文档 | 内容 |
|------|------|
| [architecture.md](docs/architecture.md) | 数据流、分层模型、两条导入链路的架构 |
| [modules.md](docs/modules.md) | 每个文件/目录的职责与关键抽象 |
| [design_constraints.md](docs/design_constraints.md) | 单向数据流、就地修改、注册规则、维度一致性等硬约束 |
| [config_reference.md](docs/config_reference.md) | `.env` 与 `qdrant.yml` 配置项说明 |
| [build.md](docs/build.md) | 依赖、CLI 用法、启动与验证方式 |
| [web.md](docs/web.md) | Web 前后端架构、REST API 路由 |
| [code_style.md](docs/code_style.md) | 语言版本、注释与命名约定 |
| [review_checklist.md](docs/review_checklist.md) | 提交前的自查清单 |

使用与详解：

| 文档 | 内容 |
|------|------|
| [USAGE.md](USAGE.md) | 完整使用说明：环境准备、CLI 参数、使用场景、输出文件、故障排查 |
| [INTRODUCTION.md](INTRODUCTION.md) | 各模块的详细设计说明（数据模型、提取器、分块、嵌入、向量库） |

专题分析（`docs/`）：

| 文档 | 内容 |
|------|------|
| [chunk-structures.md](docs/chunk-structures.md) | 三类块的字段级结构，以及它在 Qdrant 中的落盘形态 |
| [qdrant-data-audit.md](docs/qdrant-data-audit.md) | `i2stream_collection` 全量数据实测报告 |
| [qdrant-test-im-chunks-audit.md](docs/qdrant-test-im-chunks-audit.md) | `test_im_chunks` 全量数据实测报告 |
| [query/chunk-aware-search-strategy.md](docs/query/chunk-aware-search-strategy.md) | 基于当前块结构的检索策略设计 |

## 开发约定

- 修改代码前先读 [CLAUDE.md](CLAUDE.md)（协作规则与关键约束）和 [docs/review_checklist.md](docs/review_checklist.md)。
- 新增提取器 / 嵌入后端 / 向量库时，必须在对应的工厂映射中注册，否则不会被调度。
- `DocAwareChunk` 在各阶段就地修改，不得覆盖上游阶段写入的字段。
- 大 chunk 中不允许包含 mini-chunk（`Embedder` 会抛 `RuntimeError` 拦截）。
- 日志模式必须写入独立 collection，不得与文档库混用。
- 提交前运行测试：`pip install -r requirements-dev.txt && pytest`。

## 测试

```bash
pip install -r requirements-dev.txt
pytest                      # 全部用例
pytest tests/test_chunking.py -v
```

测试只覆盖不依赖外部服务的纯逻辑（数据模型、提取器、分块、日志模式解析、Qdrant 配置解析）；嵌入模型下载与 Qdrant 实连不在用例范围内，需要时应通过 mock 隔离。
