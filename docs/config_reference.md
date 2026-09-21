# chunk 配置参考

## `.env` 关键项

| 变量 | 说明 |
|------|------|
| `EMBEDDING_BACKEND` | `openai` 或 `local` |
| `EMBEDDING_MODEL` | 模型名，如 `text-embedding-3-small`、`BAAI/bge-large-zh-v1.5` |
| `EMBEDDING_BATCH_SIZE` | 批处理大小 |
| `OPENAI_API_KEY` | OpenAI API Key |
| `OPENAI_MODEL` | LLM 模型，默认 `gpt-4o-mini` |
| `LOCAL_EMBEDDING_DEVICE` | 本地模型设备：`cpu` / `cuda` / `cuda:0` |
| `LOCAL_EMBEDDING_NORMALIZE` | 是否 L2 归一化 |
| `CHUNK_SIZE` | 标准 chunk token 上限 |
| `MINI_CHUNK_SIZE` | mini-chunk token 上限 |
| `ENABLE_LARGE_CHUNKS` | 是否启用大 chunk |
| `LARGE_CHUNK_RATIO` | 大 chunk 合并比例 |
| `ENABLE_CONTEXTUAL_RAG` | 是否启用 Contextual RAG |
| `USE_LLM` | 是否使用 LLM 生成上下文 |
| `ENABLE_ENRICHMENT` | 是否启用 BGE 预富化 |
| `ENABLE_IMAGE_PROCESSING` | 是否启用图片处理（OCR / Vision） |
| `IMAGE_PROCESSOR_BACKEND` | 图片处理后端：`local` 或 `remote` |
| `IMAGE_PROCESSOR_MODEL` | 远程模型名，如 `gpt-4o-mini`、`mimo-v2.5` |
| `IMAGE_PROCESSOR_API_KEY` | 远程图片处理 API Key，默认回退到 `OPENAI_API_KEY` |
| `IMAGE_PROCESSOR_BASE_URL` | 远程图片处理 Base URL，如 `https://api.openai.com/v1` |
| `OCR_LANGUAGES` | 本地 OCR 语言，默认 `ch_sim,en` |
| `OCR_DEVICE` | 本地 OCR 运行设备：`cpu` / `cuda` |
| `IMAGE_CACHE_DIR` | 图片处理结果磁盘缓存目录 |
| `IMAGE_MIN_WIDTH` / `IMAGE_MIN_HEIGHT` | 跳过处理的图片最小宽高 |
| `LOG_PATTERN_COLLECTION_NAME` | 日志模式库目标 collection，默认 `log_patterns_collection` |
| `HF_ENDPOINT` | HuggingFace 镜像地址（国内环境用 `https://hf-mirror.com`） |
| `HF_HOME` | HuggingFace 模型缓存目录（本地嵌入模型下载位置） |

## `qdrant.yml`

管理 Qdrant 连接与 collection 参数：

| 字段 | 说明 |
|------|------|
| `mode` | `local` 或 `remote` |
| `path` | 本地模式数据目录 |
| `host` / `port` | 远程模式地址 |
| `collection_name` | collection 名称 |
| `distance` | 距离度量，如 `Cosine` |
| `vector_size` | 向量维度，必须与模型输出维度一致 |
| `auto_create_collection` | 是否自动创建 collection |
| `upsert_batch_size` | Qdrant 单次 upsert 批大小，默认 100（远程模式单请求 payload 上限 32MB，大文档需分批） |

## 配置加载顺序

```
CLI args > 环境变量 > .env > 硬编码默认值
```

## 常见注意点

- `.env` 默认使用 `BAAI/bge-large-zh-v1.5`（1024 维），而 `qdrant.yml` 默认 `vector_size=1536`。若使用本地模型并启用向量库存储，需将 `qdrant.yml` 的 `vector_size` 改为 `1024`。
