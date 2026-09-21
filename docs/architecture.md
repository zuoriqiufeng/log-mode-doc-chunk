# chunk 架构概览

chunk 是一个多格式文档处理与向量化管道，参考 Onyx（前 Danswer）设计，为 i2Agent 的日志分析引擎提供 RAG 服务。

## 核心数据流

```
Document File
    ↓
Extract (text + metadata + images)
    ↓
Image Processing (OCR / Vision, optional)
    ↓
Enrich (symbol detection, optional)
    ↓
Chunk (standard chunk + mini-chunk + image chunk + tabular chunk)
    ↓
Large Chunk (multipass merge)
    ↓
Contextual RAG (doc_summary + chunk_context)
    ↓
Embed (OpenAI or local model)
    ↓
Vector Store (Qdrant) / Local Save
```

数据单向流动，阶段间通过标准 `DocAwareChunk` 列表传递。

## 日志模式库数据流（log_patterns/）

独立于文档 pipeline 的第二条导入路径，面向"日志特征 → 根因 → 处置"结构化知识：

```
Log Pattern File (JSON/YAML/CSV/Excel)
    ↓
Parse (log_patterns/parsers.py → list[LogPattern])
    ↓
Chunk (log_patterns/chunker.py: 1 standard + 2~4 mini per pattern)
    ↓
Embed (复用 Embedder)
    ↓
Qdrant log_patterns_collection (payload 含 is_log_pattern + 模式专有字段)
```

- 每条模式 = 1 个 standard chunk（`chunk_level=log_pattern_standard`）+ 2~4 个 mini chunk：
  - mini-1：日志特征指纹（`log_fingerprint` + component + error_codes 拼接）
  - mini-2：根因 root_cause
  - mini-3：处置 remediation 摘要
  - mini-4（可选）：症状 symptom + 误判提示 false_positive
- standard chunk 的 `custom_payload` 携带模式专有字段（pattern_id / log_fingerprint / component / severity / error_codes / db_types / source_note / updated_at / is_log_pattern=true），由 `QdrantVectorStore.upsert_chunks()` 合并进 point payload
- mini chunk 的 `mini_chunk_payloads[i]` 与 `mini_chunk_texts[i]` 一一对应
- 目标 collection 独立（默认 `log_patterns_collection`），不复用文档库 collection；通过显式参数或 `LOG_PATTERN_COLLECTION_NAME` 覆盖
- 幂等写入：`document_id = log_pattern_{pattern_id}`，同 pattern_id 重复导入覆盖旧 point

## 数据模型层级

```
Document
    ↓
Section (TEXT | IMAGE | TABULAR)
    ↓
DocAwareChunk
    ↓
IndexChunk (with ChunkEmbedding)
```

### DocAwareChunk 关键字段

- `chunk_level`：块层级，取值为 `standard` / `mini` / `image` / `tabular` / `large`，用于明确区分 chunk 类型。
- `mini_chunk_texts`：细粒度子块，用于提升检索召回。
- `mini_chunk_offsets`：每个 mini chunk 在父 content 中的 `(start, end)` 偏移。
- `large_chunk_reference_ids`：指向合并后的大 chunk ID（multipass 索引）。
- `large_chunk_id`：standard / mini / image chunk 指向父 large chunk。
- `image_file_id`：图片块关联的本地图片文件路径。
- `doc_summary` + `chunk_context`：Contextual RAG 字段，嵌入时拼接在内容前后。
- `custom_payload`：自定义 payload 字典，写入 Qdrant 时合并进主 chunk point（日志模式库等结构化数据使用）。
- `mini_chunk_payloads`：与 `mini_chunk_texts` 一一对应的 mini chunk 自定义 payload。

### 嵌入文本组装顺序

```
title_prefix + doc_summary + content + chunk_context + metadata_suffix_semantic
```

## 设计模式

- **Strategy Pattern**：`extractors/` 按扩展名分派提取器。
- **Factory Pattern**：`embedding/factory.py`、`vector_store/factory.py` 按配置创建实例。
- **ABC + 多实现**：`BaseEmbeddingModel`（OpenAI/Local）、`BaseVectorStore`（Qdrant）、`DocumentExtractor`（各格式）。
- **Pipeline Pattern**：`pipeline.py` 编排 9 个顺序阶段。

## Qdrant Point ID

使用确定性 UUID：

```python
uuid5(NAMESPACE_DNS, f"{document_id}_{chunk_id}")
```

同一 document + chunk 始终映射到同一 point。Mini-chunk 使用：

```python
f"mini_{document_id}_{chunk_id}_{mini_idx}"
```

## Qdrant Payload 字段

主 chunk point 写入以下字段：

| 字段 | 说明 |
|------|------|
| `document_id` | 源文档标识 |
| `chunk_id` | 文档内 chunk 编号 |
| `chunk_level` | `standard` / `mini` / `image` / `tabular` / `large` |
| `section_type` | `text` / `image` / `tabular` |
| `content` | 块文本内容 |
| `blurb` | 摘要 |
| `mini_chunk_count` | 子块数量 |
| `mini_chunk_texts` | 子块文本列表 |
| `mini_chunk_offsets` | 子块偏移 |
| `large_chunk_id` | 父 large chunk ID |
| `large_chunk_reference_ids` | large chunk 子引用 |
| `image_file_id` | 图片文件路径（image chunk） |
| `doc_summary` / `chunk_context` | Contextual RAG 上下文 |
| `custom_payload` 内容 | 结构化数据的专有字段（如日志模式的 `pattern_id`、`log_fingerprint`、`component`、`severity`、`error_codes`、`db_types`、`is_log_pattern` 等） |

Mini chunk point 精简写入，保留 `parent_chunk_id`、`mini_chunk_index`、`chunk_level=mini`。若 chunk 提供 `mini_chunk_payloads`，对应 mini point 会合并其中的自定义字段。
