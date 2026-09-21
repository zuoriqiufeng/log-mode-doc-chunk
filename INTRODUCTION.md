# test_doc 项目详细介绍

## 1. 项目概述

**test_doc** 是一个多格式文档处理与向量化管道，定位是 [Onyx](https://github.com/onyx-dot-app/onyx)（原 Danswer）企业搜索平台中**文档索引流水线**的简化、可独立运行的参考实现。

### 核心目标

将任意格式的文档（PDF、Word、Markdown、HTML、纯文本等）经过以下处理阶段，最终输出带向量嵌入的语义分块（semantic chunks）：

```
文档文件
  └──► 提取文本 + 元数据 + 图片
         └──► 语义分块（标准 chunk + mini-chunk）
                └──► 大 chunk 合并（Multipass）
                       └──► Contextual RAG 上下文增强
                              └──► 向量嵌入（OpenAI / 本地模型）
                                     └──► 保存结果（JSON + TXT + NPY）
```

### 设计参考

每个模块的设计直接借鉴 Onyx 对应的核心代码：

| test_doc 模块 | Onyx 参考源 |
|---|---|
| `extractors/` | `backend/onyx/file_processing/extract_file_text.py` |
| `chunking/` | `backend/onyx/indexing/chunker.py` |
| `contextual_rag.py` | `backend/onyx/prompts/contextual_retrieval.py` |
| `embedding/` | `backend/onyx/indexing/embedder.py` |
| `pipeline.py` | `backend/onyx/indexing/indexing_pipeline.py` |

### 架构思想

- **模块化**：每个处理阶段独立成模块，职责单一
- **管道化**：数据单向流动，阶段之间通过标准数据模型传递
- **可替换**：任何阶段都可独立替换实现（如更换嵌入模型、更换分块策略）
- **配置驱动**：通过 `.env` 文件集中管理所有配置

---

## 2. 整体架构

### 2.1 模块结构图

```
test_doc/
├── models.py                 # 核心数据模型
├── multi_doc_processor.py    # CLI 入口
├── pipeline.py               # 主处理流程编排
├── contextual_rag.py         # Contextual RAG 上下文增强
├── utils.py                  # 工具函数（保存、打印、表格检测）
│
├── extractors/               # 文档提取器
│   ├── __init__.py           # EXTRACTOR_MAP + get_extractor()
│   ├── base.py               # DocumentExtractor 抽象基类
│   ├── pdf.py                # PDF 提取器
│   ├── docx.py               # Word 提取器
│   ├── html.py               # HTML 提取器
│   ├── markdown.py           # Markdown 提取器
│   └── text.py               # 纯文本 + JSON + XML + CSV + LOG
│
├── chunking/                 # 分块逻辑
│   ├── __init__.py
│   ├── text.py               # 文本分块（标准 + mini）
│   ├── image.py              # 图片分块
│   ├── tabular.py            # 表格分块
│   └── large.py              # 大 chunk 生成
│
├── embedding/                # 向量嵌入
│   ├── __init__.py           # 公共 API 导出
│   ├── models.py             # 数据模型（Embedding 类型别名）
│   ├── base.py               # BaseEmbeddingModel 抽象接口
│   ├── config.py             # .env / 环境变量配置管理
│   ├── openai_provider.py    # OpenAI API 实现
│   ├── local_provider.py     # 本地 sentence-transformers 实现
│   ├── factory.py            # create_embedding_model() 工厂
│   └── embedder.py           # Embedder 编排器
│
└── vector_store/             # 向量数据库（Qdrant）
    ├── __init__.py           # 公共 API 导出
    ├── base.py               # BaseVectorStore 抽象接口 + SearchResult
    ├── qdrant_config.py      # qdrant.yml 配置管理
    ├── qdrant_store.py       # Qdrant 实现
    └── factory.py            # create_vector_store() 工厂
```

### 2.2 数据流图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        multi_doc_processor.py (CLI)                      │
│  解析参数 ──► 调用 pipeline.process_document()                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        pipeline.py (8 步流水线)                          │
│                                                                          │
│  [1] 文档提取     extractors.get_extractor(ext).extract(file)           │
│  [2] 保存图片     写入 output/images/                                    │
│  [3] 检测表格     utils.detect_and_parse_table(text)                    │
│  [4] 构建 Document  text_sections + image_sections + table_sections     │
│  [5] 分块         chunking.text / image / tabular                       │
│       └─► Large Chunk  chunking.large.generate_large_chunks()           │
│  [6] Contextual RAG  contextual_rag.add_contextual_rag()                │
│  [7] 向量嵌入       embedding.create_embedding_model()                  │
│                     embedding.Embedder.embed_chunks()                   │
│  [8] 向量数据库     vector_store.create_vector_store().upsert_chunks()  │
│  [9] 保存结果       utils.save_results()                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型（models.py）

核心模型沿用了 Onyx 的命名和设计，使用 Python `dataclass` 定义：

```python
Document
├── id: str                          # 文档唯一标识（文件路径）
├── semantic_identifier: str         # 语义标识
├── title: str | None                # 文档标题
├── sections: list[Section]          # 段落列表
├── metadata: dict                   # 文档元数据
└── get_text_content() -> str        # 拼接所有段落文本

Section
├── type: SectionType                # TEXT | IMAGE | TABULAR
├── text: str | None                 # 文本内容
├── heading: str | None              # 段落标题
├── link: str | None                 # 链接
└── image_file_id: str | None        # 图片文件路径

DocAwareChunk
├── source_document: Document        # 所属文档
├── chunk_id: int                    # chunk 序号
├── content: str                     # 完整文本内容
├── blurb: str                       # 内容摘要（前 150 字符）
├── section_type: SectionType        # TEXT | IMAGE | TABULAR
├── title_prefix: str                # 标题前缀（用于嵌入增强）
├── mini_chunk_texts: list[str]      # 细粒度子分块
├── large_chunk_reference_ids: list[int]   # 引用的大 chunk ID
├── doc_summary: str                 # 文档摘要（Contextual RAG）
├── chunk_context: str               # chunk 位置上下文
└── section_continuation: bool       # 是否跨段落延续

IndexChunk (extends DocAwareChunk)
├── embeddings: ChunkEmbedding       # full + mini 向量
│   ├── full_embedding: Embedding    # 主向量
│   └── mini_chunk_embeddings: list[Embedding]
└── title_embedding: Embedding       # 标题向量（跨 chunk 复用）
```

### 关键字段说明

| 字段 | 说明 |
|---|---|
| `mini_chunk_texts` | 细粒度子分块，提升检索召回率。每个标准 chunk 可进一步切分为多个 mini-chunk，各自拥有独立嵌入向量 |
| `large_chunk_reference_ids` | 大 chunk 引用的标准 chunk ID 列表。Multipass 索引中，大 chunk 合并多个标准 chunk 的文本 |
| `doc_summary` | 文档级摘要，由 Contextual RAG 生成，嵌入时拼接在 content 前面 |
| `chunk_context` | chunk 在文档中的位置描述（如"Previous: xxx; Next: yyy"），嵌入时拼接在 content 后面 |
| `title_prefix` | 文档标题前缀，嵌入时放在最前面，提升标题相关性的匹配度 |
| `contextual_rag_reserved_tokens` | 为 Contextual RAG 预留的 token 配额 |

---

## 4. 文档提取层（extractors/）

### 4.1 设计模式

采用**策略模式**：

- `DocumentExtractor`（`extractors/base.py`）定义抽象接口：
  ```python
  extract(file_path) -> tuple[str, dict[str, Any], list[tuple[bytes, str]]]
  ```
- 各格式实现具体提取逻辑
- `EXTRACTOR_MAP`（`extractors/__init__.py:16`）根据文件扩展名自动分派提取器
- 未知扩展名时，尝试检测是否为纯文本，回退到 `TextExtractor`

### 4.2 支持的格式

| 扩展名 | 提取器 | 依赖库 | 特性 |
|---|---|---|---|
| `.pdf` | `PdfExtractor` | `pypdf`, `PIL` | 提取文本、元数据、嵌入图片 |
| `.docx` `.doc` | `DocxExtractor` | `python-docx` | 段落、表格、图片，处理合并单元格 |
| `.html` `.htm` | `HtmlExtractor` | `beautifulsoup4` | 清理标签，保留链接，处理 Doctype |
| `.md` `.markdown` | `MarkdownExtractor` | `markdownify` | 移除 YAML frontmatter，HTML → Markdown |
| `.txt` `.text` `.conf` `.cfg` `.ini` `.yml` `.yaml` `.sql` | `TextExtractor` | `chardet` | 自动编码检测，`ONYX_METADATA` 解析 |
| `.json` | `JsonExtractor` | — | 格式化输出，提取 title/name 字段 |
| `.xml` `.xsl` `.xsd` | `XmlExtractor` | — | 去除标签，提取 `<title>` |
| `.csv` `.tsv` | `CsvExtractor` | — | 解析为表格文本（含 CSV 格式 + 可读格式） |
| `.log` | `LogExtractor` | — | 提取时间戳范围作为元数据 |

### 4.3 ONYX_METADATA 解析

纯文本提取器支持从文件第一行提取 Onyx 风格的元数据：

```text
<!--ONYX_METADATA={"Title": "文档标题", "Author": "作者"}-->
# 或
#ONYX_METADATA={"Title": "文档标题"}
```

提取后自动从内容中移除，写入 `Document.metadata`。

---

## 5. 分块层（chunking/）

### 5.1 文本分块（chunking/text.py）

使用 **`chonkie`** 库的 `SentenceChunker` 进行基于句子的语义分块：

```python
# 标准 chunk：默认 512 tokens（按字符估算 token × 4）
chunk_splitter = SentenceChunker(
    tokenizer="character",
    chunk_size=chunk_token_limit * 4,
    chunk_overlap=0,
)

# mini-chunk：默认 150 tokens
mini_chunk_splitter = SentenceChunker(
    tokenizer="character",
    chunk_size=mini_chunk_size * 4,
    chunk_overlap=0,
)
```

每个文本 chunk 包含：
- `title_prefix`：文档标题前缀，嵌入时用于增强语义匹配
- `section_continuation`：`True` 表示该 chunk 起始位置不是段落开头
- `mini_chunk_texts`：细粒度子分块列表

### 5.2 图片分块（chunking/image.py）

从文档中提取的嵌入图片保存到 `output/images/`，每个图片生成一个 `DocAwareChunk`：
- `section_type = IMAGE`
- `image_file_id` 指向保存的图片文件路径
- `content` 为图片引用描述

### 5.3 表格分块（chunking/tabular.py）

通过 `utils.detect_and_parse_table()` 启发式检测表格区域，解析为 CSV 格式：
- 表格作为一个独立的 `TABULAR` chunk
- 同时从文本段落中移除表格行，避免重复

### 5.4 大 chunk 生成（chunking/large.py）

**Multipass 索引策略**：每 `ratio`（默认 4）个标准 chunk 合并为一个 Large Chunk。

```
Chunk0  Chunk1  Chunk2  Chunk3  ──►  LargeChunk0 (refs: [0,1,2,3])
Chunk4  Chunk5  Chunk6  Chunk7  ──►  LargeChunk1 (refs: [4,5,6,7])
```

Large Chunk 特点：
- `is_large_chunk = True`
- **不包含** mini-chunks
- `large_chunk_reference_ids` 记录合并了哪些标准 chunk
- 检索时优先匹配 Large Chunk，匹配度不足时回落到标准 chunk

参考 Onyx `generate_large_chunks()` 实现。

---

## 6. Contextual RAG（contextual_rag.py）

为每个 chunk 添加**文档级**和**位置级**上下文，显著提升检索时的语义匹配质量。

### 6.1 生成内容

| 字段 | 来源 | 嵌入位置 |
|---|---|---|
| `doc_summary` | 文档整体摘要 | content **前面** |
| `chunk_context` | chunk 在文档中的位置描述 | content **后面** |

### 6.2 嵌入时的文本拼接顺序

```
title_prefix + doc_summary + content + chunk_context + metadata_suffix_semantic
```

### 6.3 两种生成模式

#### LLM 模式（`--use-llm`）

调用 OpenAI API，使用 Onyx 官方 Prompt 模板：

- **DOCUMENT_SUMMARY_PROMPT**：要求 LLM 生成整个文档的简短摘要
- **CONTEXTUAL_RAG_PROMPT1 + PROMPT2**：要求 LLM 描述 chunk 在文档中的位置上下文

#### 规则模式（默认）

无需 LLM，零成本运行：

- **文档摘要**：取文档前 300 字符的标题+内容截断
- **Chunk 上下文**：提取相邻 chunk 的 blurb，格式为 `"Previous: xxx; Next: yyy"`

---

## 7. 向量嵌入层（embedding/）

按照 Onyx 的分层架构，将原本 monolithic 的 `embedder.py` 拆分为 8 个职责清晰的模块：

```
embedding/
├── models.py           # 纯数据模型（Embedding = list[float]）
├── base.py             # BaseEmbeddingModel 抽象接口 + 富化内容生成
├── config.py           # 集中配置管理（.env / 环境变量）
├── openai_provider.py  # OpenAI API 实现
├── local_provider.py   # sentence-transformers 本地实现
├── factory.py          # create_embedding_model() 工厂
└── embedder.py         # Embedder 编排器
```

### 7.1 抽象接口（base.py）

```python
class BaseEmbeddingModel(ABC):
    @abstractmethod
    def encode(self, texts: list[str]) -> list[Embedding]:
        """将文本列表编码为向量列表"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称"""
```

### 7.2 嵌入流程（embedder.py）

参考 Onyx `DefaultIndexingEmbedder.embed_chunks()`：

1. **构建扁平文本列表**：
   ```
   [chunk1_enriched, chunk1_mini1, chunk1_mini2, chunk2_enriched, ...]
   ```

2. **批量编码**：通过 `BaseEmbeddingModel.encode()` 统一接口调用

3. **Title 缓存**：
   - 提取所有 chunk 的唯一文档标题集合
   - 只编码一次，通过字典映射回各 chunk
   - 避免同一文档的多个 chunk 重复编码标题

4. **结果映射**：
   - 第 1 个向量 → `full_embedding`
   - 后续向量 → `mini_chunk_embeddings[]`
   - 标题向量 → `title_embedding`

### 7.3 支持的嵌入后端

| 后端 | 实现类 | 模型示例 | 说明 |
|---|---|---|---|
| **OpenAI** | `OpenAIEmbeddingModel` | `text-embedding-3-small`, `text-embedding-3-large` | 通过 OpenAI SDK 调用 `/v1/embeddings`，支持批处理 |
| **本地** | `LocalEmbeddingModel` | `all-MiniLM-L6-v2`, `BAAI/bge-large-zh-v1.5` | 直接加载 Hugging Face 模型，支持 cpu/cuda 设备选择和 L2 归一化 |

### 7.4 配置优先级

```
CLI 参数（如 --embedding-backend local）
    ↓ 最高优先级
环境变量（如 EMBEDDING_BACKEND=local）
    ↓
.env 文件（test_doc/.env）
    ↓
硬编码默认值
    ↓ 最低优先级
```

### 7.5 向量数据库层（vector_store/）

test_doc 使用 **Qdrant** 作为向量数据库，将嵌入后的 chunk 持久化存储，支持语义检索。

```
vector_store/
├── base.py           — BaseVectorStore 抽象接口 + SearchResult
├── qdrant_config.py  — qdrant.yml 配置加载
├── qdrant_store.py   — Qdrant 实现（本地/远程双模式）
└── factory.py        — create_vector_store() 工厂
```

**核心接口** (`BaseVectorStore`)：
- `collection_exists()` / `create_collection(dimension)` — Collection 管理
- `upsert_chunks(chunks)` — 批量写入/更新 IndexChunk
- `search(query_embedding, top_k, filters)` — 向量相似度搜索
- `delete_by_document_id(document_id)` — 按文档删除
- `delete_by_chunk_id(document_id, chunk_id)` — 按 chunk 删除
- `get_chunk_count()` — 统计 chunk 数量

**QdrantVectorStore** 特点：
- **本地模式**：直接读写文件系统 (`path=./qdrant_data`)，无需外部服务
- **远程模式**：连接 Qdrant 服务器，支持 gRPC/HTTP、API Key 认证
- **自动创建 Collection**：根据首个 chunk 的向量维度自动推断并创建
- **确定性 UUID**：使用 `uuid5` 生成稳定的 point id，确保同一 document + chunk 始终映射到同一 Qdrant point

**与 Onyx 的对应关系**：
| test_doc | Onyx 参考源 |
|---|---|
| `vector_store/base.py` | `backend/onyx/document_index/interfaces_new.py` |
| `vector_store/qdrant_store.py` | Qdrant 社区驱动（Onyx 使用 Vespa） |

---

## 8. 配置系统

### 8.1 .env 文件

`test_doc/.env` 集中管理所有配置：

```bash
# 嵌入后端: openai | local
EMBEDDING_BACKEND=openai

# 嵌入模型名称
EMBEDDING_MODEL=text-embedding-3-small

# 嵌入批处理大小
EMBEDDING_BATCH_SIZE=100

# OpenAI 配置
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini

# 本地模型配置
LOCAL_EMBEDDING_DEVICE=cpu
LOCAL_EMBEDDING_NORMALIZE=false
```

### 8.2 配置加载机制

- `multi_doc_processor.py` 在模块导入时自动加载 `.env`
- `embedding/config.py` 在模块导入时自动加载 `.env`
- 使用 `override=False`，保证环境变量可以覆盖 `.env` 中的值

---

## 9. 与 Onyx 的关系

test_doc 是 Onyx 核心索引流水线的**精简复刻**，保留了最核心的"文档 → 语义分块 → 向量"链路，移除了企业级功能。

### 9.1 核心差异

| 维度 | Onyx | test_doc |
|---|---|---|
| **定位** | 完整企业搜索平台 | 文档处理与向量化管道 |
| **数据存储** | PostgreSQL + Vespa 向量数据库 | 本地文件系统（JSON + NPY） |
| **本地模型推理** | 自研 model server（FastAPI + 异步 HTTP） | 直接调用 `sentence-transformers` |
| **分块器** | 自定义 tokenizer + 滑动窗口 | `chonkie` 库的 SentenceChunker |
| **多租户** | 支持 | 不支持 |
| **Web UI** | 有 | 无 |
| **错误处理** | 完整的重试、熔断、失败隔离 | 简化版，打印警告并继续 |
| **部署** | Docker Compose / K8s | 单个 Python 脚本 |

### 9.2 代码对应关系

| test_doc | Onyx 参考源 | 复刻程度 |
|---|---|---|
| `extractors/` | `backend/onyx/file_processing/extract_file_text.py` | 功能等价，简化错误处理 |
| `chunking/text.py` | `backend/onyx/indexing/chunker.py` | 使用 chonkie 替代自定义 tokenizer |
| `chunking/large.py` | `backend/onyx/indexing/chunking/document_chunker.py` | 直接复刻 |
| `contextual_rag.py` | `backend/onyx/prompts/contextual_retrieval.py` | Prompt 原文照搬 |
| `embedding/embedder.py` | `backend/onyx/indexing/embedder.py` | 核心逻辑复刻，简化重试 |
| `embedding/openai_provider.py` | `search_nlp_models.py` (CloudEmbedding) | 简化版同步调用 |
| `embedding/local_provider.py` | `backend/model_server/encoders.py` | 直接加载替代 HTTP 调用 |
| `pipeline.py` | `backend/onyx/indexing/indexing_pipeline.py` | 简化版，无数据库写入 |
