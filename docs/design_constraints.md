# chunk 关键设计约束

## 数据流单向性

Pipeline 阶段只能向前传递数据，后面阶段不能反向依赖前面阶段。

## DocAwareChunk 就地修改

各阶段就地修改 chunk 字段，必须确保不会覆盖前面阶段写入的值（例如 `chunk_context` 不要被 embedding 阶段覆盖）。

## Large chunk 不包含 mini-chunk

`Embedder` 会以 `RuntimeError` 强制保证大 chunk 不包含 mini-chunk。

## 配置优先级

```
CLI args > Environment variables > .env file > Hardcoded defaults
```

Qdrant 配置单独放在 `qdrant.yml` 中。

## Qdrant 维度一致性

`qdrant.yml` 中的 `vector_size` 必须与实际嵌入模型输出维度一致。例如：

- `BAAI/bge-large-zh-v1.5` → 1024 维
- `text-embedding-3-small` → 1536 维

## 默认 collection 名

未在 `qdrant.yml` 或 Web 配置中指定时的兜底值，统一取自
`vector_store/qdrant_config.py` 的 `DEFAULT_COLLECTION_NAME`（当前为 `chunk_collection`）。
新增调用点时**引用该常量**，不要再写字符串字面量——历史上该默认值曾在 6 处副本中漂移。

> 注意：本机 `qdrant_data/` 中已有的旧集合（`test_doc_chunks` 等）不受此常量影响，
> 它们只在显式配置 `collection_name` 时才会被访问。旧数据要用就把名字写进 `qdrant.yml`。

## 大 chunk 编号与 point id

- Qdrant point id = `uuid5(f"{document_id}_{chunk_id}")`，因此 **`chunk_id` 必须在同一文档内全局唯一**。
- `generate_large_chunks()` 返回的大 chunk，其 `chunk_id` 只是组内第一个成员的占位值；
  真正编号由 `pipeline.py` 在合并后统一重分配（`lc.chunk_id = chunk_id`），重分配后
  `large_chunk_id == chunk_id`（自指）。改这段逻辑时必须保证编号不重复，否则两个块会互相覆盖。
- 大块的 `large_chunk_id` 是**自指**的，所以判断"某块是否被合并进大块"不能只看
  `large_chunk_id is not None`，必须同时排除 `chunk_level == "large"`（`searcher.py` 用
  `is_large_chunk` 先行分支来规避同一问题）。

## Qdrant Payload 一致性

写入 Qdrant 的 chunk point 必须包含：

- `chunk_level`：明确标记层级
- `section_type`：区分 text / image / tabular
- `image_file_id`：image chunk 必填
- `mini_chunk_offsets`：standard chunk 有 mini 时必填

结构化数据（如日志模式）通过 `DocAwareChunk.custom_payload` / `mini_chunk_payloads` 扩展 payload，由 `QdrantVectorStore.upsert_chunks()` 自动合并，不得绕过这两个字段直接改 point 结构。

## 日志模式库约束

- 日志模式默认写入独立 collection（`log_patterns_collection`），**不得**复用 `qdrant.yml` 中的文档库 collection，避免 payload schema 混杂。
- `log_fingerprint` 在 payload 中保持 `string[]`；语义嵌入文本由 `LogPattern.fingerprint_text` 拼接生成。
- 每条模式固定生成 1 个 standard chunk（`chunk_level=log_pattern_standard`）+ 2~4 个 mini chunk；不生成 large chunk、不走 Contextual RAG。
- 幂等性依赖 `document_id = log_pattern_{pattern_id}` 的确定性 UUID，导入侧不得随机生成 document_id。

## 提取器注册

新增格式提取器需要：

1. 实现 `DocumentExtractor`。
2. 在 `extractors/__init__.py` 的 `EXTRACTOR_MAP` 中注册扩展名映射。

## 嵌入后端扩展

新增嵌入后端需要：

1. 实现 `BaseEmbeddingModel`。
2. 在 `embedding/factory.py` 的 `EMBEDDING_BACKENDS` 中注册。

## 向量存储扩展

新增向量存储后端需要：

1. 实现 `BaseVectorStore`。
2. 在 `vector_store/factory.py` 中注册。

## Enrichment 顺序

`enrich_document_text()` 生成的是独立 `Section`，不修改原文；**不要**在表格检测之前调用它。

## 混合检索降级

`Searcher.hybrid_search()` 在语义分数低于阈值时，会降级为 payload 关键词/内容子串匹配。

## API Key 安全

`.env` 中包含 `OPENAI_API_KEY` 和 `IMAGE_PROCESSOR_API_KEY`，禁止提交真实 key 到版本控制。

## 图片处理

- 远程图片处理器按图片数量计费，大批量处理前建议先用本地后端验证。
- 图片处理失败时返回空字符串，不能中断 pipeline。
- 图片 chunk 的 `content` 由 `build_image_chunk_text()` 统一构建。
