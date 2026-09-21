# chunk 模块职责

| 文件/目录 | 职责 | 关键抽象 |
|-----------|------|----------|
| `image_processing/` | 图片处理：本地 OCR / 远程 Vision | `BaseImageProcessor`、`create_image_processor()`、`ImageCache` |
| `image_processing/local_processor.py` | 本地 EasyOCR 实现 | `EasyOCRImageProcessor` |
| `image_processing/remote_processor.py` | 远程 OpenAI Vision 实现 | `OpenAIVisionProcessor` |
| `image_processing/factory.py` | 处理器工厂 | `create_image_processor()` |
| `image_processing/config.py` | 图片处理配置读取 | `ImageProcessorConfig` |
| `image_processing/utils.py` | 图片工具：base64、小图过滤、chunk 文本构建 | `encode_image_to_base64()`、`build_image_chunk_text()` |
| `models.py` | 核心数据模型 | `Document`、`Section`、`DocAwareChunk`、`IndexChunk`、`ChunkEmbedding` |
| `pipeline.py` | 9 步流程编排 | `process_document()` |
| `multi_doc_processor.py` | CLI 入口 | argparse → `process_document()` → `save_results()` |
| `enrichment.py` | BGE 预富化：符号串检测 + 语义锚点标注 | `detect_annotations()`、`enrich_document_text()`、`Annotation` |
| `extractors/` | 按格式提取文本/元数据/图片 | `DocumentExtractor` ABC → `EXTRACTOR_MAP` 分派 |
| `extractors/pdf.py` | PDF 提取 | `PdfExtractor` |
| `extractors/docx.py` | DOCX 提取：文本、表格、内嵌图片占位符 | `DocxExtractor` |
| `extractors/doc.py` | 旧版 DOC 提取 | `DocExtractor` |
| `extractors/html.py` | HTML 清理提取 | `HtmlExtractor` |
| `extractors/markdown.py` | Markdown 提取：保留标题层级、代码块、本地/远程图片占位符 | `MarkdownExtractor` |
| `extractors/text.py` | 文本/JSON/XML/CSV/日志提取 | `TextExtractor` 等 |
| `extractors/image.py` | 图片元数据提取 | `ImageExtractor` |
| `extractors/excel.py` | Excel 提取 | `ExcelExtractor` |
| `chunking/text.py` | 文本分块 + mini chunk 切分 | `chunk_text_sections()`、`split_mini_chunks()`，基于 `chonkie.SentenceChunker` |
| `chunking/log.py` | 日志分块 | `LogChunker`：按 Drain 模板聚类 |
| `chunking/large.py` | 大 chunk 合并 | `generate_large_chunks(ratio=4)` |
| `chunking/image.py` | 图片分块 | `chunk_image_section()` |
| `chunking/tabular.py` | 表格分块 | `chunk_tabular_section()` |
| `contextual_rag.py` | 上下文增强 | `add_contextual_rag()`：LLM 或规则模式 |
| `embedding/models.py` | 嵌入类型定义 | `Embedding`、`EmbedRequest`、`EmbedResponse` |
| `embedding/base.py` | 嵌入模型基类 | `BaseEmbeddingModel` |
| `embedding/openai_provider.py` | OpenAI 嵌入 | `OpenAIEmbeddingModel` |
| `embedding/local_provider.py` | 本地嵌入 | `LocalEmbeddingModel` |
| `embedding/factory.py` | 模型工厂 | `create_embedding_model()` |
| `embedding/config.py` | 集中读取 `.env` | `EmbeddingConfig` |
| `embedding/embedder.py` | Chunk → IndexChunk | `Embedder.embed_chunks()`，title 缓存 |
| `vector_store/base.py` | 向量存储基类 | `BaseVectorStore`、`SearchResult` |
| `vector_store/qdrant_config.py` | Qdrant 配置 | `QdrantConfig` |
| `vector_store/qdrant_store.py` | Qdrant 实现：写入主 chunk + mini chunk，payload 含 `chunk_level`、`mini_chunk_offsets`、`image_file_id` | `QdrantVectorStore` |
| `vector_store/factory.py` | 存储工厂 | `create_vector_store()` |
| `vector_store/searcher.py` | 检索逻辑 | `Searcher`：`hybrid_search()` |
| `log_patterns/` | 日志模式库导入包（独立于文档 pipeline） | — |
| `log_patterns/models.py` | 日志模式数据模型 | `LogPattern`（字段与设计文档 3.1 对齐） |
| `log_patterns/parsers.py` | JSON/YAML/CSV/TSV/Excel 解析 | `BaseLogPatternParser`、`get_parser()`、字段别名归一化 |
| `log_patterns/chunker.py` | 1 standard + 2~4 mini 分块 | `LogPatternChunker` |
| `log_patterns/payload.py` | Qdrant payload 构建 | `build_pattern_payload()` |
| `log_patterns/importer.py` | 解析 → 分块 → 嵌入 → 入库编排 | `import_log_patterns()`、`import_log_patterns_from_data()` |
| `log_patterns/cli.py` | 日志模式导入 CLI | `python -m log_patterns.cli` |
| `import_log_patterns.py` | 顶层便捷入口 | 等价于 `python -m log_patterns.cli` |
| `utils.py` | 工具函数：保存结果、表格检测、ZIP 解压、文本清理 | `save_results()`、`detect_and_parse_table()`、`safe_extract_zip()`、`clean_text()` |
| `query.py` | 独立查询 CLI | `Searcher.search()` |
| `docs/query/chunk-aware-search-strategy.md` | 查询策略设计文档 | — |
| `docs/qdrant-test-im-chunks-audit.md` | Qdrant 实测报告 | — |
| `web/app.py` | Flask 后端 API | 58002 端口 |
| `web/frontend.py` | 前端静态服务 + 代理 | 58001 端口 |
| `web/start.py` | 同时启动前后端 | — |
| `web/static/` | SPA 静态资源 | `index.html`、`app.js`、`style.css` |
