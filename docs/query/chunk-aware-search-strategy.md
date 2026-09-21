# 基于当前分块结构的查询策略设计

> 日期: 2026-07-21（初稿）
> 依据: `test_im_chunks` 实测数据（114 points，2 文档：Markdown + DOCX）
> 适用版本: 已包含 `chunk_level`、`mini_chunk_offsets`、`image_file_id` 改进
> 更新: 2026-09-18 对齐当前代码 — 新增 §1.5 实现现状对照、§2.6 混合检索、§6.4 实施优先级；块结构全量参考见 `docs/chunk-structures.md`

---

## 1. 当前数据分层（Qdrant 落盘现状）

### 1.1 分块层级

| chunk_level | 类型 | 数量 | 关键特征 | 检索定位 |
|-------------|------|-----:|----------|----------|
| `mini` | 小块 | 60 | 独立向量点，`parent_chunk_id` 指向 standard | 精准匹配层 |
| `standard` | 标准块 | 16 | 文本主块，含 `mini_chunk_texts` / `mini_chunk_offsets` | 主力召回层 |
| `image` | 图片块 | 27 | `section_type=image`，含图片占位符或 OCR/描述文本 | 多模态检索层 |
| `large` | 大块 | 11 | 聚合多个 standard 块，`large_chunk_reference_ids` | 上下文扩展层 |
| `tabular` | 表格行块 | 0 | `section_type=tabular`，表格每行一块（该快照无表格文档，管线支持） | 结构化数据层 |
| `log_pattern_standard` | 日志模式块 | — | 结构化 `custom_payload`，写入独立 `log_patterns_collection`，不进本 collection | 日志模式层 |

### 1.2 按文档拆分

| 文档 | 总点数 | standard | mini | image | large |
|------|-------:|---------:|-----:|------:|------:|
| 崖山部署.md | 41 | 8 | 31 | 0 | 2 |
| *.docx | 73 | 8 | 29 | 27 | 9 |

### 1.3 关键字段可用性

- `chunk_id`: 文档内唯一，跨文档会重复
- `chunk_level`: 6 个枚举值 — `standard` / `mini` / `large` / `image` / `tabular` / `log_pattern_standard`（全量字段见 `docs/chunk-structures.md`）
- `section_type`: `text` / `image` / `tabular`
- `mini_chunk_count`: standard 块子块数量
- `mini_chunk_offsets`: 每个 mini 在父 content 中的 `(start, end)`
- `large_chunk_id`: standard → large 的父指针
- `large_chunk_reference_ids`: large → standards 的子引用
- `image_file_id`: 图片块关联的本地文件路径
- `doc_summary` / `chunk_context`: Contextual RAG 增强文本

### 1.4 与旧数据的核心差异

- 不再有图片占位符污染 large chunk：docx 图片已独立为 `chunk_level=image` 的 chunk。
- 所有 standard 块均携带 mini chunks（最少 1 个）。
- large chunk 内容正常，可直接作为上下文返回。
- mini chunk 有独立向量点和精确偏移，支持命中位置回源。

### 1.5 实现现状对照（2026-09-18 对代码逐项核查）

| 方案条目 | 状态 | 说明 |
|---|---|---|
| §2.2 mini-first 精准检索 | ❌ 未实现 | `Searcher.search` 全层级混搜（无 `chunk_level` 过滤），`hit_mini` 偏移回源未实现 |
| §2.3 standard + image 混合 | ❌ 未实现 | image/tabular 不加分层直接参与 ANN |
| §2.4 parent_expand / §2.5 large-only | ❌ 未实现 | 现状只有"命中后向 large 聚合"（`_aggregate_by_large_chunk`），无主动 large-only 检索与扩展参数 |
| §4.1 推荐 7 个 payload 索引 | ❌ 0 个建成 | `_ensure_payload_indexes` 只建 `keywords`(keyword) / `data_types`(keyword) / `content`(text) 3 个；`chunk_level` 等字段能过滤但走全表扫描 |
| §6.2 `strategy` 参数 | ❌ 未实现 | `/api/query` 仅 `query`/`top_k`/`filters`；`/api/search` 连 `filters` 都没有 |
| §5 结果格式 | ⚠️ 部分 | `/api/query` 已返回 `chunk_level`/`source_chunk_ids`/`doc_summary`/`chunk_context`；`/api/search` 缺这 4 个 |
| 符号串/错误码检索（初稿未覆盖） | ✅ 代码已有 | `hybrid_search()` + `keywords`/`data_types` payload 写入（2026-09-18 pipeline `[4.6]`）——**但全项目零调用方，Web 端点全走纯 `search`**，见 §2.6 |
| large 聚合、`document_id` 过滤、mini 独立点/offsets | ✅ 已实现 | `searcher.py` / `_build_filter` / `qdrant_store.upsert_chunks` |

> 注意：`keywords`/`data_types` 兜底依赖 `--enrich`（`ENABLE_ENRICHMENT=true`）重新灌入；`i2stream_collection` 中 2026-09-18 之前灌入的旧数据这两字段仍为空数组。

---

## 2. 推荐查询策略

### 2.1 总体流程

```
查询文本
  → 向量化
  → 并行检索 mini / standard / image（按策略选择）
  → 去重 + 父子聚合
  → 按需扩展为 large 上下文
  → 返回带 chunk_level / image_file_id / offsets 的结果
```

### 2.2 策略一：mini-first 精准检索（默认推荐）

**定位**：先用 mini 块做 ANN，命中后返回父 standard 块，并标注命中位置。

**实现要点**：

1. 优先搜索 `chunk_level=mini`。
2. 对命中 mini 点，通过 `parent_chunk_id` + `document_id` 反查对应 standard 块。
3. 返回 standard 块完整 `content`，并在结果中携带：
   - `hit_mini_index`: 命中的 mini 序号
   - `hit_mini_offset`: mini 在 content 中的 `(start, end)`
   - `hit_mini_text`: 命中的 mini 文本
4. 同一 standard 块多次命中时，保留得分最高的 mini，其余去重。
5. 如果 mini 召回不足，fallback 到 standard 层补充。

**适用场景**：事实检索、参数/步骤定位、长段落中的具体句子查询。

**优点**：
- 命中粒度细，便于高亮
- 避免长 standard 块中 irrelevant 部分干扰排序

---

### 2.3 策略二：standard + image 混合检索

**定位**：标准块做主力召回，同时把图片块作为独立候选参与语义匹配。

**实现要点**：

1. ANN 搜索同时覆盖：
   - `chunk_level=standard`
   - `chunk_level=image`
2. 命中 image 块时：
   - 若已开启图片处理，content 为 OCR/描述文本，直接返回；
   - 若未开启，content 为 `[嵌入图片: xxx.png]`，可返回 `image_file_id` 供前端展示原图。
     > ⚠️ **未采纳**（2026-09-21）：已确认 i2Agent / 前端无「区分图片来源」或「取原图路径」需求，纯文本检索即可，因此 `RetrievalResult` 未加 `image_file_id` 字段。此为**设想**而非缺失功能。相关设计说明见 `../chunk-structures.md` §2.1。
3. standard 命中后，可按 `large_chunk_id` 扩展上下文。
4. 结果排序时混合标准块与图片块的相似度分数。

**适用场景**：问题可能涉及文档截图、流程图、错误截图的检索。

**注意**：图片块向量质量取决于图片处理后端（OCR/Vision）是否启用和可用。

---

### 2.4 策略三：parent_expand 上下文增强

**定位**：用 standard 或 mini 召回后，扩展为 large 块提供更完整上下文。

**实现要点**：

1. 先执行策略一或策略二得到候选 standard / image / mini。
2. 对命中的 standard 块，若 `large_chunk_id` 存在：
   - 拉取对应 large 块；
   - 用 large 块内容替换或补充 standard 块内容返回。
3. 同一 large 块下多个 standard 命中时，按最高分去重，large 块只返回一次。
4. 未归并到 large 的 standard / image 单独返回。

**适用场景**：通用问答、需要上下文的总结性问题。

**优点**：减少碎片感，返回更连贯的上下文。

---

### 2.5 策略四：large-only 长上下文检索

**定位**：直接检索 large 块，适合宽泛主题查询。

**实现要点**：

1. 只搜索 `chunk_level=large`。
2. 命中后直接返回 large 块 `content`。
3. 可通过 `large_chunk_reference_ids` 反查子 standard 块作为补充证据。

**适用场景**："这篇文档讲了什么"、"总结一下部署流程" 等宏观问题。

**注意**：large 块数量少（当前 11 个），召回率可能低于 mini/standard 策略。

---

### 2.6 策略五：hybrid_search 混合检索（代码已实现，未接入 Web）

**定位**：语义分数不够时的精确兜底，解决 `-4002` 这类纯符号串 BGE 得分≈0 的问题。初稿未覆盖此场景，2026-09-18 补入。

**已有实现**（`vector_store/searcher.py: hybrid_search()`）：

1. BGE 语义搜索，分数 ≥ `semantic_threshold`（默认 0.30）的结果保留；
2. 低于阈值时调用 `_search_by_keywords()` 兜底：
   - 首选 Qdrant `content` 全文索引查询（v1.10+ 路径）；
   - 异常时 fallback 为 scroll + Python 端 `content` 子串 / `payload.keywords` 子串匹配；
3. 合并去重后按分数排序。

**payload 支撑**（pipeline `[4.6]`，需 `--enrich` / `ENABLE_ENRICHMENT=true`）：

- `keywords`（string[]）：富化标注词，如 `错误码 -4002 (IAERR_LOG_SEQ)`；
- `data_types`（string[]）：`error_code` / `version` / `database` / `port` / `config_param` / `uuid` / `ip` / `filepath`，也可经 `filters={"data_types": ...}` 直接过滤。

**当前缺口**：`hybrid_search` 无任何调用方——`/api/query`、`/api/search`、`query.py` 全部走纯 `search()`。接入是 P1 优先级（见 §6.4）。

**适用场景**：错误码、版本号、端口、UUID、配置参数等符号串精确查询。

---

## 3. 推荐默认组合

| 查询类型 | 推荐策略 | 说明 |
|----------|----------|------|
| 事实/参数/步骤 | **mini-first** | 精准、可高亮 |
| 截图/图表相关 | **standard + image** | 多模态召回 |
| 通用问答 | **mini-first + parent_expand** | 精准 + 上下文 |
| 宏观总结 | **large-only** 或 **parent_expand** | 长上下文 |
| 符号串/错误码/端口 | **hybrid_search**（§2.6，唯一已实现的专用策略） | BGE 低分兜底 + keywords 精确匹配 |

默认建议：**mini-first + parent_expand**：
- 先搜 mini 保证精准；
- 命中不足时 fallback standard；
- 最终按 `large_chunk_id` 聚合并扩展为 large 上下文。

> 实现状态：该默认组合依赖 §6 改造，当前生产链路实际只有"全层级 ANN + large 聚合"一条路径。

---

## 4. Qdrant 过滤与索引设计

### 4.1 推荐 Payload 索引（含现状与优先级，2026-09-18 更新）

| 字段 | Schema | 用途 | 现状 | 优先级 |
|------|--------|------|------|--------|
| `chunk_level` | keyword | 按层级筛选（分层检索的前提） | ❌ 未建 | **P0** |
| `section_type` | keyword | 区分 text / image / tabular | ❌ 未建 | **P0** |
| `document_id` | keyword | 文档过滤 | ❌ 未建（可用，但全表扫描） | **P0** |
| `chunk_id` | integer | 父子反查 | ❌ 未建 | P1 |
| `parent_chunk_id` | integer | mini → standard | ❌ 未建 | P1 |
| `large_chunk_id` | integer | standard → large | ❌ 未建 | P1 |
| `mini_chunk_count` | integer | 长文本筛选 | ❌ 未建 | P2 |
| `keywords` | keyword | 符号串兜底匹配 | ✅ 已建 | — |
| `data_types` | keyword | 按富化类型过滤 | ✅ 已建 | — |
| `content` | text | 全文兜底 | ✅ 已建 | — |

> 已建的 3 个见 `_ensure_payload_indexes()`（`vector_store/qdrant_store.py:91-113`）。

### 4.2 过滤条件示例

**只搜 mini + standard（默认）**：

```json
{
  "should": [
    { "key": "chunk_level", "match": { "value": "standard" } },
    { "key": "chunk_level", "match": { "value": "mini" } }
  ]
}
```

**包含图片的混合检索**：

```json
{
  "should": [
    { "key": "chunk_level", "match": { "value": "standard" } },
    { "key": "chunk_level", "match": { "value": "mini" } },
    { "key": "chunk_level", "match": { "value": "image" } }
  ]
}
```

**只搜长文本 standard（mini_chunk_count >= 3）**：

```json
{
  "must": [
    { "key": "chunk_level", "match": { "value": "standard" } },
    { "key": "mini_chunk_count", "range": { "gte": 3 } }
  ]
}
```

**按文档过滤**：

```json
{
  "must": [
    { "key": "document_id", "match": { "value": "..." } }
  ]
}
```

---

## 5. 命中结果格式建议

查询 API 返回每个结果应包含：

```json
{
  "chunk_id": 5,
  "chunk_level": "standard",
  "section_type": "text",
  "document_id": "...",
  "title": "...",
  "content": "...",
  "blurb": "...",
  "score": 0.892,
  "large_chunk_id": 9,
  "mini_chunk_count": 4,
  "image_file_id": null,
  "hit_mini": {
    "index": 1,
    "text": "...",
    "offset": [400, 952]
  }
}
```

如果是 image 块：

```json
{
  "chunk_level": "image",
  "section_type": "image",
  "image_file_id": ".../image_000_image1.png",
  "content": "[嵌入图片: image1.png]"
}
```

> 现状（2026-09-18）：`/api/query` 已返回 `chunk_level` / `source_chunk_ids` / `doc_summary` / `chunk_context`；`/api/search`（i2Agent 兼容格式）目前只有 `content` / `score` / `metadata{document_id, chunk_id, title, section_type, is_large_chunk}`，缺上述 4 字段；`hit_mini` 结构尚未实现。

---

## 6. 实施建议

### 6.1 Searcher 改造

按依赖顺序（2026-09-18 重排）：

0. **先补索引**（§4.1 的 P0 三项）——否则 `chunk_level` 等过滤全部走全表扫描；
1. **接线 `hybrid_search`**（§2.6）——代码现成，`/api/query` 加参数或对符号串查询自动降级，改动最小、收益直接；

在 `vector_store/searcher.py` 中新增/调整：

1. `search_mini_first(query, top_k, filters)`：
   - 先查 mini；
   - 命中后反查 standard；
   - 组装 `hit_mini` 信息。

2. `search_standard_with_image(query, top_k, filters)`：
   - 同时查 standard 和 image；
   - image 结果单独标记 `image_file_id`。

3. `expand_to_large(results)`：
   - 对 standard 命中按 `large_chunk_id` 聚合；
   - 拉取 large 块并替换/补充返回。

4. `deduplicate_by_large_chunk(results)`：
   - 同一 large 块下多个命中只保留最佳。

### 6.2 Web API 扩展

`/api/query` 建议新增参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `strategy` | string | `mini_first` | `mini_first` / `standard_image` / `large_only` / `parent_expand` / `hybrid` |
| `include_images` | bool | true | 是否召回 image 块 |
| `expand_to_large` | bool | true | 是否扩展为 large 上下文 |
| `top_k` | int | 5 | 返回结果数 |
| `filters` | dict | null | 按 document_id 等过滤 |

### 6.3 前端展示

- 结果列表按 `chunk_level` 显示不同图标：text / image / large。
- image 块可点击展示原图（使用 `image_file_id`）。
- mini 命中结果可高亮对应文本区域（使用 `hit_mini.offset`）。
- large 块结果可折叠展开，显示子 standard 列表。

### 6.4 实施优先级（2026-09-18 重排）

| 优先级 | 事项 | 成本 | 收益 |
|---|---|---|---|
| **P0** | 补建 §4.1 P0 三个索引（`chunk_level` / `section_type` / `document_id`） | 极低（`_ensure_payload_indexes` 加 3 行） | 所有过滤检索免全表扫描，分层检索解锁 |
| **P1** | `hybrid_search` 接入 `/api/query` | 低（函数现成，加参数或自动降级） | 符号串查询立刻可用（keywords payload 已在写入） |
| **P2** | 实现 mini-first + `hit_mini` 偏移回源 | 中（新增检索函数 + parent 反查） | 精准召回与命中高亮 |
| **P3** | `strategy` 参数 + parent_expand / large-only | 中 | 完整覆盖 §2 四策略 |
| **P3** | `/api/search` 补齐缺失 4 字段 | 低 | 与 §5 结果格式对齐 |

---

## 7. 当前数据下的策略验证

以 `test_im_chunks` 为例：

- mini-first：60 个候选点，命中后可映射到 16 个 standard 父块。
- standard + image：16 + 27 = 43 个候选点，适合混合查询。
- parent_expand：11 个 large 块可覆盖全部 standard / image。
- large-only：11 个候选点，适合宏观问题但召回率有限。

建议默认 **mini-first + parent_expand**，兼顾精准度和上下文完整性。

> 以上数字为 2026-07-21 `test_im_chunks` 快照，仅作策略推演示例；当前生产 collection 为 `i2stream_collection`（`qdrant.yml`），实际分层分布以 `docs/qdrant-data-audit.md` 为准。
