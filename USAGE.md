# test_doc 使用说明

## 目录

1. [环境准备](#1-环境准备)
2. [快速开始](#2-快速开始)
3. [配置详解](#3-配置详解)
4. [CLI 参数](#4-cli-参数)
5. [使用场景](#5-使用场景)
6. [输出文件说明](#6-输出文件说明)
7. [故障排查](#7-故障排查)

---

## 1. 环境准备

### 1.1 Python 版本

需要 Python 3.9+。

### 1.2 安装依赖

```bash
cd test_doc

# 基础依赖（必须）
pip install chonkie beautifulsoup4 markdownify python-docx pypdf Pillow chardet

# OpenAI 嵌入后端（可选，使用 OpenAI 时必须）
pip install openai

# 本地嵌入后端（可选，使用本地模型时必须）
pip install sentence-transformers

# .env 配置支持（推荐安装）
pip install python-dotenv
```

或使用项目已有的虚拟环境：

```bash
source .venv/bin/activate
```

### 1.3 配置 OpenAI API Key

编辑 `test_doc/.env` 文件：

```bash
OPENAI_API_KEY=sk-your-actual-key-here
```

或设置环境变量：

```bash
export OPENAI_API_KEY=sk-your-actual-key-here
```

---

## 2. 快速开始

### 2.1 最简用法

处理单个文档，仅分块不嵌入：

```bash
python multi_doc_processor.py document.md
```

输出默认保存在 `chunks_output/` 目录。

### 2.2 指定输出目录

```bash
python multi_doc_processor.py document.md my_output
```

### 2.3 启用向量嵌入

```bash
python multi_doc_processor.py document.md output --embed
```

---

## 3. 配置详解

### 3.1 .env 配置文件

`test_doc/.env` 是核心配置文件，所有嵌入相关参数均可在此配置：

```bash
# ============================================================================
# 嵌入后端选择
# ============================================================================
# 可选值: openai | local
EMBEDDING_BACKEND=openai

# ============================================================================
# 嵌入模型名称
# ============================================================================
# OpenAI 可选模型:
#   - text-embedding-3-small  (默认, 1536维, 最经济)
#   - text-embedding-3-large  (3072维, 精度最高)
#   - text-embedding-ada-002  (旧版, 1536维)
#
# 本地模型可选 (sentence-transformers):
#   - all-MiniLM-L6-v2              (384维, 英文, 速度快)
#   - BAAI/bge-large-zh-v1.5        (1024维, 中文, 精度高)
#   - sentence-transformers/all-mpnet-base-v2  (768维, 英文)
#   - nomic-ai/nomic-embed-text-v1  (768维, 多语言)
EMBEDDING_MODEL=text-embedding-3-small

# ============================================================================
# 批处理大小
# ============================================================================
# OpenAI 默认 100, 本地模型默认 32
# 根据显存/网络情况调整
EMBEDDING_BATCH_SIZE=100

# ============================================================================
# OpenAI 配置
# ============================================================================
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini

# ============================================================================
# 本地模型配置 (仅 EMBEDDING_BACKEND=local 时生效)
# ============================================================================
# 运行设备: cpu | cuda | cuda:0 | cuda:1 | mps
LOCAL_EMBEDDING_DEVICE=cpu

# 是否进行 L2 归一化 (true/false)
# 归一化后向量长度一致，便于余弦相似度计算
LOCAL_EMBEDDING_NORMALIZE=false
```

### 3.2 配置优先级

当同一配置项存在多种来源时，按以下优先级生效：

```
CLI 参数  >  环境变量  >  .env 文件  >  硬编码默认值
```

**示例**：`.env` 中配置 `EMBEDDING_BACKEND=openai`，但命令行指定 `--embedding-backend local`，则实际使用 `local`。

### 3.3 环境变量覆盖

临时覆盖 `.env` 配置，不修改文件：

```bash
# 临时切换到本地模型
EMBEDDING_BACKEND=local EMBEDDING_MODEL=all-MiniLM-L6-v2 \
  python multi_doc_processor.py doc.md out --embed

# 临时切换 OpenAI 模型
EMBEDDING_MODEL=text-embedding-3-large \
  python multi_doc_processor.py doc.md out --embed
```

---

## 4. CLI 参数

### 4.1 完整参数列表

```
usage: multi_doc_processor.py [-h] [--no-contextual-rag] [--use-llm]
                              [--chunk-size CHUNK_SIZE]
                              [--mini-chunk-size MINI_CHUNK_SIZE]
                              [--no-large-chunks] [--embed]
                              [--embedding-backend {openai,local}]
                              [--embedding-model EMBEDDING_MODEL]
                              [--embedding-device EMBEDDING_DEVICE]
                              [--embedding-batch-size EMBEDDING_BATCH_SIZE]
                              [--normalize-embeddings]
                              [--enable-vector-store]
                              file [output]
```

### 4.2 参数详解

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `file` | 位置参数 | — | **输入文件路径**（必填） |
| `output` | 位置参数 | `chunks_output` | **输出目录** |
| `--no-contextual-rag` | 标志 | 启用 | 禁用上下文增强 |
| `--use-llm` | 标志 | 禁用 | 使用 OpenAI LLM 生成上下文（需配置 `OPENAI_API_KEY`） |
| `--chunk-size` | 整数 | 512 | 标准 chunk 的 token 上限 |
| `--mini-chunk-size` | 整数 | 150 | mini-chunk 的 token 上限 |
| `--no-large-chunks` | 标志 | 启用 | 禁用大 chunk 生成 |
| `--embed` | 标志 | 禁用 | **启用向量嵌入** |
| `--embedding-backend` | 选择 | `openai` | 嵌入后端：`openai` 或 `local` |
| `--embedding-model` | 字符串 | `.env` 配置 | 嵌入模型名称 |
| `--embedding-device` | 字符串 | `cpu` | 本地模型设备（仅 `local` 后端） |
| `--embedding-batch-size` | 整数 | `.env` 配置 | 批处理大小 |
| `--normalize-embeddings` | 标志 | `false` | L2 归一化（仅 `local` 后端） |
| `--enable-vector-store` | 标志 | 禁用 | 将嵌入结果写入 Qdrant 向量数据库 |
| `--enrich` | 标志 | `false` | **BGE 预富化**：自动检测错误码/版本号/配置参数等符号串，追加语义锚点标注块 |

---

## 5. 使用场景

### 5.1 场景一：基础分块（无嵌入）

适合只需要文档分块结果，不需要向量化的场景：

```bash
python multi_doc_processor.py report.pdf output/report \
  --no-contextual-rag \
  --no-large-chunks
```

**输出**：
- `chunks.json` — 分块元数据
- `chunk_000.txt` — 各 chunk 文本内容
- `images/` — 提取的嵌入图片

### 5.2 场景二：OpenAI 向量化

使用 OpenAI API 进行嵌入，适合有 API Key 的用户：

```bash
# 1. 配置 .env
# OPENAI_API_KEY=sk-xxx
# EMBEDDING_MODEL=text-embedding-3-small

# 2. 运行
python multi_doc_processor.py document.md output \
  --embed \
  --embedding-backend openai
```

**特点**：
- 无需本地 GPU
- 向量质量高
- 需要网络连接和 API 费用

### 5.3 场景三：本地模型向量化

使用本地 sentence-transformers 模型，适合隐私敏感或无网络环境：

```bash
# 1. 安装依赖
pip install sentence-transformers

# 2. 配置 .env
# EMBEDDING_BACKEND=local
# EMBEDDING_MODEL=all-MiniLM-L6-v2
# LOCAL_EMBEDDING_DEVICE=cpu

# 3. 运行
python multi_doc_processor.py document.md output \
  --embed \
  --embedding-backend local \
  --embedding-model all-MiniLM-L6-v2 \
  --embedding-device cpu
```

**首次运行**会自动下载模型到 `~/.cache/torch/sentence_transformers/`。

**使用 GPU 加速**：

```bash
python multi_doc_processor.py document.md output \
  --embed \
  --embedding-backend local \
  --embedding-device cuda
```

### 5.4 场景四：中文文档处理

中文文档建议使用中文优化模型：

```bash
python multi_doc_processor.py chinese_doc.pdf output \
  --embed \
  --embedding-backend local \
  --embedding-model BAAI/bge-large-zh-v1.5 \
  --normalize-embeddings
```

或使用 OpenAI 模型（多语言支持）：

```bash
python multi_doc_processor.py chinese_doc.pdf output \
  --embed \
  --embedding-backend openai \
  --embedding-model text-embedding-3-large
```

### 5.5 场景五：启用 Contextual RAG（LLM 模式）

使用 OpenAI LLM 为每个 chunk 生成高质量上下文：

```bash
python multi_doc_processor.py research_paper.pdf output \
  --embed \
  --use-llm \
  --chunk-size 512
```

**说明**：
- `--use-llm` 需要配置 `OPENAI_API_KEY`
- LLM 会为每个 chunk 生成 `doc_summary` 和 `chunk_context`
- 嵌入时会将上下文拼接在 content 前后，提升检索精度
- 会产生额外的 API 调用费用

### 5.6 场景六：规则模式 Contextual RAG（零成本）

不调用 LLM，使用基于规则的上下文生成：

```bash
python multi_doc_processor.py research_paper.pdf output \
  --embed \
  --chunk-size 512
```

**说明**：
- 不添加 `--no-contextual-rag`，默认启用规则模式
- 文档摘要取前 300 字符
- Chunk 上下文取相邻 chunk 的 blurb
- **完全免费**，无需 API Key

### 5.7 场景七：写入 Qdrant 向量数据库

将嵌入结果写入 Qdrant 向量数据库，支持本地模式和远程模式：

```bash
# 本地模式（无需外部服务）
python multi_doc_processor.py document.md output \
  --embed \
  --enable-vector-store
```

**配置** `qdrant.yml`：
```yaml
mode: local
path: ./qdrant_data
collection_name: test_doc_chunks
distance: cosine
vector_size: 1536
auto_create_collection: true
```

**说明**：
- `--enable-vector-store` 必须与 `--embed` 同时使用
- 首次运行会自动创建 Collection（当 `auto_create_collection: true`）
- 本地模式数据存储在 `./qdrant_data` 目录
- 支持通过 `qdrant.yml` 切换为远程 Qdrant 服务器

### 5.8 场景八：调整分块粒度

根据文档类型调整分块大小：

```bash
# 短文档/摘要场景：小 chunk，更多 mini-chunk
python multi_doc_processor.py short_notes.md output \
  --chunk-size 256 \
  --mini-chunk-size 80 \
  --embed

# 长文档/论文场景：大 chunk，减少数量
python multi_doc_processor.py thesis.pdf output \
  --chunk-size 1024 \
  --mini-chunk-size 256 \
  --embed
```

### 5.9 场景九：禁用大 chunk

标准 chunk 足够时使用，减少处理时间：

```bash
python multi_doc_processor.py document.md output \
  --embed \
  --no-large-chunks
```

### 5.10 场景十：BGE 预富化 — 增强符号串搜索命中

**背景：** BGE（bge-large-zh-v1.5）是句子级语义模型，对纯数字/符号串（如 `-4002`、`19c`、`1521`）编码为低信息量向量，搜索时 score=0。启用预富化后，错误码/版本号/配置参数等符号串会被自动检测并追加到 chunk 中作为语义锚点。

```bash
# 同时启用嵌入和预富化
python multi_doc_processor.py error_codes.md output --embed --enrich

# 结合向量数据库写入
python multi_doc_processor.py error_codes.md output --embed --enrich --enable-vector-store
```

**检测类型：**

| 类型 | 示例输入 | 标注输出 |
|------|----------|----------|
| 错误码 | `IAERR_LOG_SEQ \| 4002 \| fatal` | `关联错误码: 错误码 -4002 (IAERR_LOG_SEQ)` |
| 版本号 | `Oracle 19c`, `i2Stream 9.1.4` | `涉及版本: Oracle 19c, i2Stream 9.1.4` |
| 数据库 | `Oracle`, `DB2`, `达梦` | `数据库: Oracle, DB2` |
| 配置参数 | `DB2CODEPAGE=1208` | `配置参数: DB2CODEPAGE=1208` |
| UUID | `9DED5F94-...` | `规则UUID: 9DED5F94-...` |
| IP 地址 | `192.168.30.102` | `IP地址: 192.168.30.102` |
| 端口号 | `port 1521` | `端口: 1521` |
| 文件路径 | `/hdd/demo/logs/log` | `文件路径: /hdd/demo/logs/log` |

**预期效果：** 搜索 `-4002` 的 BGE score 从 0.000 → 0.55+。

**Payload 侧同步写入：** 启用后除追加文本标注块外，每个 chunk（含 mini-chunk）还会按自身内容把标注写入 Qdrant payload：

- `keywords`（string[]）— 富化后的标注词（如 `错误码 -4002 (IAERR_LOG_SEQ)`），供 `hybrid_search` 关键词兜底精确匹配；
- `data_types`（string[]）— 检测器类型名（`error_code` / `version` / `database` / `port` / `config_param` / `uuid` / `ip` / `filepath`），供按类型过滤，例如 `store.search(..., filters={"data_types": "error_code"})`。

**环境变量：** 设置 `ENABLE_ENRICHMENT=true` 在 `.env` 中可省略 CLI `--enrich` 参数。

### 5.11 场景十一：混合检索（BGE + 关键词兜底）

当 Qdrant 向量库中已写入数据后，使用 `Searcher.hybrid_search()` 进行混合检索：

```python
from embedding import create_embedding_model, Embedder
from vector_store import create_vector_store
from vector_store.searcher import Searcher

store = create_vector_store()
model = create_embedding_model(backend="local", model_name="BAAI/bge-large-zh-v1.5")
searcher = Searcher(store, model)

# 混合检索：BGE 语义搜索 + payload 关键词兜底
# 当 BGE score < 0.30 时自动降级为 keywords 精确匹配
results = searcher.hybrid_search("-4002", top_k=5, semantic_threshold=0.30)
for r in results:
    print(f"score={r.score:.3f} | {r.content[:100]}")

# 纯语义搜索
results = searcher.search("-4002", top_k=5)
```

### 5.12 旧十：批量处理脚本

处理多个文档：

```bash
#!/bin/bash
for file in docs/*.pdf docs/*.md; do
    basename=$(basename "$file" | cut -d. -f1)
    python multi_doc_processor.py "$file" "output/$basename" --embed
done
```

---

## 6. 输出文件说明

### 6.1 目录结构

```
output/
├── chunks.json              # 所有 chunk 的元数据
├── chunk_000.txt            # Chunk 0 的文本内容
├── chunk_001.txt            # Chunk 1 的文本内容
├── ...
├── images/                  # 提取的嵌入图片
│   ├── image_000_xxx.png
│   └── ...
└── embeddings/              # 向量文件（仅 --embed 时生成）
    ├── chunk_000_full.npy       # Chunk 0 主向量
    ├── chunk_000_title.npy      # Chunk 0 标题向量
    ├── chunk_000_mini_0.npy     # Chunk 0 Mini-0 向量
    ├── chunk_000_mini_1.npy     # Chunk 0 Mini-1 向量
    └── ...
```

### 6.2 chunks.json 结构

```json
[
  {
    "chunk_id": 0,
    "section_type": "text",
    "content_length": 1256,
    "blurb": "文档开头摘要...",
    "title_prefix": "文档标题\n",
    "section_continuation": false,
    "is_large_chunk": false,
    "large_chunk_id": null,
    "large_chunk_reference_ids": [],
    "mini_chunk_count": 3,
    "mini_chunk_texts": ["...", "...", "..."],
    "doc_summary": "本文档是关于...",
    "chunk_context": "Previous: ...; Next: ...",
    "embedding_dim": 1536,
    "has_full_embedding": true,
    "mini_embedding_count": 3,
    "source_document_id": "document.md",
    "source_document_title": "文档标题"
  }
]
```

### 6.3 chunk_xxx.txt 结构

```text
# Chunk 0
# Type: text
# Blurb: 文档开头摘要...
# Source: document.md
------------------------------------------------------------
[chunk 的完整文本内容]

============================================================
# Doc Summary: 文档摘要...
# Chunk Context: 位置上下文...

============================================================
# Mini-chunks (3 个):

--- Mini 0 ---
[mini-chunk 文本]

--- Mini 1 ---
[mini-chunk 文本]
```

### 6.4 向量文件（.npy）

使用 NumPy 格式保存，可直接用 numpy 读取：

```python
import numpy as np

# 读取 chunk 0 的主向量
full_emb = np.load("output/embeddings/chunk_000_full.npy")
print(full_emb.shape)  # (1536,) 或 (384,) 等，取决于模型

# 读取 chunk 0 的标题向量
title_emb = np.load("output/embeddings/chunk_000_title.npy")

# 读取 chunk 0 的第一个 mini-chunk 向量
mini_emb = np.load("output/embeddings/chunk_000_mini_0.npy")
```

---

## 7. 故障排查

### 7.1 常见问题

#### Q1: `ModuleNotFoundError: No module named 'chonkie'`

**原因**：缺少分块库。

**解决**：
```bash
pip install chonkie
```

#### Q2: `ModuleNotFoundError: No module named 'openai'`

**原因**：使用 `--embed --embedding-backend openai` 但未安装 openai 包。

**解决**：
```bash
pip install openai
# 或在 .env 中切换为本地模型: EMBEDDING_BACKEND=local
```

#### Q3: `RuntimeError: 未配置 OpenAI API Key`

**原因**：使用 OpenAI 后端但未配置 API Key。

**解决**：
```bash
# 方法 1: 编辑 .env
echo "OPENAI_API_KEY=sk-your-key" >> .env

# 方法 2: 环境变量
export OPENAI_API_KEY=sk-your-key

# 方法 3: 切换到本地模型
python multi_doc_processor.py doc.md out --embed --embedding-backend local
```

#### Q4: `RuntimeError: sentence-transformers 包未安装`

**原因**：使用 `--embedding-backend local` 但未安装 sentence-transformers。

**解决**：
```bash
pip install sentence-transformers
```

#### Q5: `ModuleNotFoundError: No module named 'python-docx'`

**原因**：处理 Word 文档时缺少依赖。

**解决**：
```bash
pip install python-docx
```

#### Q6: `ModuleNotFoundError: No module named 'pypdf'`

**原因**：处理 PDF 时缺少依赖。

**解决**：
```bash
pip install pypdf Pillow
```

#### Q7: 嵌入失败但程序没有崩溃

**现象**：输出中出现 `[WARN] 嵌入失败: ...`，但其他结果正常保存。

**原因**：这是设计行为。pipeline 中嵌入步骤被 `try/except` 包裹，失败时打印警告并继续，确保分块结果仍可保存。

**排查**：
1. 检查网络连接（OpenAI 后端）
2. 检查 API Key 是否有效
3. 检查模型名称是否正确

#### Q8: 如何验证向量是否正确生成？

```python
import json
import numpy as np

# 读取元数据
with open("output/chunks.json") as f:
    chunks = json.load(f)

# 检查第一个 chunk
chunk = chunks[0]
print(f"Chunk ID: {chunk['chunk_id']}")
print(f"Embedding dim: {chunk['embedding_dim']}")
print(f"Mini embeddings: {chunk['mini_embedding_count']}")

# 读取向量
emb = np.load("output/embeddings/chunk_000_full.npy")
print(f"Vector shape: {emb.shape}")
print(f"Vector dtype: {emb.dtype}")
```

#### Q9: `ModuleNotFoundError: No module named 'qdrant_client'`

**原因**：使用 `--enable-vector-store` 但未安装 qdrant-client。

**解决**：
```bash
pip install qdrant-client pyyaml
```

#### Q10: 向量数据库写入失败但嵌入成功

**现象**：`[WARN] 向量数据库写入失败: ...`

**原因**：
1. `qdrant.yml` 配置错误（如本地路径不存在）
2. 向量维度与 Collection 配置不匹配

**解决**：
1. 检查 `qdrant.yml` 中的 `mode`、`path`、`host`、`port` 配置
2. 确保 `vector_size` 与嵌入模型维度一致
3. 删除旧的 `./qdrant_data` 目录后重试

### 7.2 性能优化建议

| 场景 | 建议 |
|---|---|
| 处理大量文档 | 使用本地模型 + GPU（`--embedding-device cuda`） |
| 网络不稳定 | 使用本地模型，避免 API 调用 |
| 内存不足 | 减小 `--chunk-size` 和 `--embedding-batch-size` |
| 追求精度 | OpenAI `text-embedding-3-large` + `--use-llm` |
| 追求速度 | 本地 `all-MiniLM-L6-v2` + `--no-contextual-rag` |
| 中文文档 | 本地 `BAAI/bge-large-zh-v1.5` 或 OpenAI `text-embedding-3-large` |

### 7.3 完整依赖清单

根据使用场景选择性安装：

```bash
# 核心依赖（必须）
pip install chonkie beautifulsoup4 markdownify python-docx pypdf Pillow chardet

# OpenAI 嵌入
pip install openai

# 本地嵌入
pip install sentence-transformers

# .env 支持
pip install python-dotenv

# Qdrant 向量数据库
pip install qdrant-client pyyaml

# 如需使用 numpy 读取 .npy 向量文件
pip install numpy
```
