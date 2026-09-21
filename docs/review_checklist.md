# chunk Review Checklist

修改代码前对照以下清单检查影响范围。

## Pipeline 数据流

- [ ] 各阶段是否保持单向数据流？
- [ ] `DocAwareChunk` 就地修改时是否覆盖了前面阶段设置的字段（如 `chunk_context`）？
- [ ] Large chunk 是否不包含 mini-chunk？
- [ ] `chunk_level` 是否在所有 chunk 类型中正确设置（standard/mini/image/tabular/large）？
- [ ] `mini_chunk_offsets` 是否与 `mini_chunk_texts` 一一对应？

## 图片处理

- [ ] 新增/修改提取器时，图片占位符格式是否为 `【PIC:{index}】`？
- [ ] DOCX 提取器是否兼容合并单元格表格？
- [ ] Markdown 提取器是否正确保留标题层级、代码块、本地/远程图片占位符？
- [ ] 远程图片处理器是否配置了合理的重试策略？
- [ ] Qdrant payload 中 image chunk 是否携带 `image_file_id`？

## 模型一致性

- [ ] `Embedding = list[float]` 在 `models.py` 和 `embedding/models.py` 中是否保持一致？

## 提取器

- [ ] 新增/修改提取器时是否更新了 `extractors/__init__.py` 中的 `EXTRACTOR_MAP`？

## 嵌入后端

- [ ] 新增嵌入后端时是否实现了 `BaseEmbeddingModel`？
- [ ] 是否在 `embedding/factory.py` 的 `EMBEDDING_BACKENDS` 中注册？

## 向量存储后端

- [ ] 新增向量存储后端时是否实现了 `BaseVectorStore`？
- [ ] 是否在 `vector_store/factory.py` 中注册？

## Qdrant

- [ ] `qdrant.yml` 中的 `vector_size` 是否与嵌入模型输出维度一致？
- [ ] Payload 索引是否通过 `_ensure_payload_indexes()` 创建，而非 `qdrant.yml`？
- [ ] 大 payload 是否依赖 `upsert_batch_size` 分批写入，而非单次 upsert？

## 日志模式库

- [ ] 新增/修改模式字段时是否同步更新 `LogPattern`、解析器 `_FIELD_ALIASES` 和 `build_pattern_payload()`？
- [ ] `log_fingerprint` 是否保持 `string[]`（payload 中），未在存储层拼成字符串？
- [ ] 每条模式是否仍为 1 standard + 2~4 mini，未生成 large chunk？
- [ ] 导入是否默认写入 `log_patterns_collection`，未污染文档库 collection？
- [ ] `custom_payload` / `mini_chunk_payloads` 改动是否影响现有文档 pipeline 的 payload 结构？

## 安全

- [ ] `.env` 中的 `OPENAI_API_KEY` 是否被意外提交？

## Enrichment

- [ ] 是否在表格检测之前调用了 `enrich_document_text()`？（不应这样做）
- [ ] 生成的 annotation 是否作为独立 `Section` 追加，而非修改原文？

## 检索

- [ ] 修改 `_search_by_keywords` 时是否同时考虑 Qdrant v1.10+ 路径和 scroll fallback？
- [ ] 修改混合检索逻辑时是否保持语义搜索 + 关键词降级的行为？
