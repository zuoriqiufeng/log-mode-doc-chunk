# 分块类型与块结构参考

> 日期: 2026-09-18
> 依据: 当前源码逐文件核对（`models.py`、`chunking/*`、`log_patterns/*`、`embedding/*`、`vector_store/*`、`utils.py`）
> 适用范围: 文档管线、日志模式库两条链路的全部块结构

---

## 1. 数据模型分层总览

```
Section（提取产物，3 种类型）
  └──► DocAwareChunk（分块产物，内存对象，22 个字段）
         ├── 富化 [4.6] 写入 custom_payload（keywords / data_types）
         ├── 日志模式分块器直接构造 custom_payload / mini_chunk_payloads
         └──► IndexChunk（嵌入产物 = DocAwareChunk + ChunkEmbedding）
                └──► Qdrant point（主 point + 每个 mini 一个独立 point）
                       └── payload（扁平化字段 + custom_payload 合并）
```

各阶段（`pipeline.py`）对 `DocAwareChunk` 只做**原地修改、单向传递**：

| 阶段 | 写入的字段 |
|---|---|
| 分块（text/image/tabular） | `content`、`blurb`、`section_type`、`chunk_level`、`title_prefix`、`section_continuation`、`mini_chunk_texts`、`mini_chunk_offsets`、`image_file_id` |
| 大块生成 `[7]` | `is_large_chunk`、`chunk_level="large"`、`large_chunk_id`、`large_chunk_reference_ids`（互写：large ↔ 子标准块） |
| 预富化 `[4.5]` | 追加标注块 Section（进 content） |
| 预富化 payload 侧 `[4.6]` | `custom_payload["keywords"]`、`custom_payload["data_types"]`、`mini_chunk_payloads[i]` |
| Contextual RAG `[8]` | `doc_summary`、`chunk_context` |
| 嵌入 `[9]` | `DocAwareChunk` → 复制为 `IndexChunk`（全字段拷贝，`custom_payload` 不丢），写 `embeddings`、`title_embedding` |
| 向量入库 `[10]` | payload 扁平化 + `payload.update(custom_payload)` |

---

### 1.1 实例：一个 standard 块的三副面孔

先建立直观印象。设想文档 `word/3.docx`（标题 `i2Stream 部署指南`）分块后得到第 5 块，富化与 Contextual RAG 均启用，它在系统里**同时以三种形态存在**：

```
内存里 1 个 DocAwareChunk 对象
   │  嵌入阶段
   ├─► 3 条编码输入 ─► 4 个向量（full + 2 mini + title）
   │  入库阶段
   └─► Qdrant 里 3 个 point（1 主 + 2 mini）
          磁盘上   1 行 chunks.json + 1 个 chunk_005.txt + 4 个 .npy
```

#### 形态一：内存对象（`DocAwareChunk`，只列有值的字段）

```python
DocAwareChunk(
    # ── 身份与内容 ──
    source_document = Document(id="word/3.docx", title="i2Stream 部署指南", ...),
    chunk_id  = 5,                          # 文档内第 6 块（0 起）
    content   = "3.2 数据库配置\n\n部署前需设置 DB2CODEPAGE=1208，……",  # 约 2000 字正文
    blurb     = "3.2 数据库配置\n\n部署前需设置 DB2CODE…",              # 前 150 字摘要

    # ── 类型与定位 ──
    section_type         = "text",
    chunk_level          = "standard",      # 不是 large/image/tabular
    section_continuation = True,            # 不是文档开头（idx=5 > 0）
    image_file_id        = None,

    # ── 嵌入增强文本 ──
    title_prefix = "i2Stream 部署指南\n",    # 拼在嵌入输入最前
    doc_summary  = "本文档介绍 i2Stream 的部署与配置流程…",   # Contextual RAG 文档摘要
    chunk_context= "Previous: 安装依赖…; Next: 启动服务…",    # Contextual RAG 相邻块
    metadata_suffix_semantic = "",          # 恒空（预留）

    # ── 大块指针（双向）──
    large_chunk_id            = 7,          # 本块被合并进 7 号大块
    large_chunk_reference_ids = [],         # 自己不是大块 → 空
    is_large_chunk            = False,

    # ── mini 三件套（本块切出 2 个 mini）──
    mini_chunk_texts   = ["部署前需设置 DB2CODEPAGE=1208…", "监听端口 1521 需确认…"],
    mini_chunk_offsets = [(812, 1390), (1391, 1985)],   # 各 mini 在 content 里的 [start,end)

    # ── 结构化 payload（富化 [4.6] 按本块内容检测写入）──
    custom_payload = {
        "keywords":   ["DB2CODEPAGE=1208", "错误码 -4002", "1521"],
        "data_types": ["config_param", "error_code", "port"],
    },
    mini_chunk_payloads = [
        {"keywords": ["DB2CODEPAGE=1208"], "data_types": ["config_param"]},  # mini0 含配置参数
        {},                                                                  # mini1 无标注
    ],

    # ── 以下保持默认（本例无值）──
    # source_links=None, metadata_suffix_keyword="", contextual_rag_reserved_tokens=0
)
```

> `chunk_id=5`、`large_chunk_id=7`、offsets 数值仅为示意，说明**谁指向谁、值长什么样**。

#### 形态二：嵌入时拼出的 3 条编码输入

```
full（主向量）:
  "i2Stream 部署指南\n" + doc_summary + content + chunk_context + ""
  = "i2Stream 部署指南\n本文档介绍…3.2 数据库配置\n\n部署前需设置…Previous: …"
                                                              ◄── 富化拼接，一个字符串 ──►

mini0（裸文本，不套富化公式）:  "部署前需设置 DB2CODEPAGE=1208…"
mini1（裸文本）:                "监听端口 1521 需确认…"

title（同文档所有块复用一次）:  "i2Stream 部署指南"
```

每条输入编码为一个 1024 维向量（`bge-large-zh-v1.5`）→ `full_embedding`×1 + `mini_chunk_embeddings`×2 + `title_embedding`×1。

#### 形态三：Qdrant 里的 3 个 point

**主 point**（id = `uuid5("word/3.docx_5")`，确定性生成）——payload 是形态一字段的**扁平投影**：

```json
{
  "document_id": "word/3.docx", "chunk_id": 5,
  "content": "3.2 数据库配置\n\n部署前需设置 DB2CODEPAGE=1208，……",
  "blurb": "3.2 数据库配置\n\n部署前需设置 DB2CODE…",
  "section_type": "text", "title": "i2Stream 部署指南",
  "chunk_level": "standard", "is_large_chunk": false, "is_mini_chunk": false,
  "large_chunk_id": 7, "large_chunk_reference_ids": [],
  "mini_chunk_count": 2,
  "mini_chunk_texts": ["部署前需设置…", "监听端口…"],
  "mini_chunk_offsets": [[812,1390],[1391,1985]],
  "doc_summary": "本文档介绍…", "chunk_context": "Previous: …",
  "image_file_id": null,
  "keywords": ["DB2CODEPAGE=1208", "错误码 -4002", "1521"],   // custom_payload 合并进来
  "data_types": ["config_param", "error_code", "port"],
  "mini_chunk_embeddings": [[...1024维...], [...1024维...]],   // 冗余携带 mini 向量
  "title_embedding": [...1024维...]
}
```

**mini point ×2**（id = `uuid5("mini_word/3.docx_5_0")`）——小 payload，只带定位 + 裸文本 + 自己的向量：

```json
{ "document_id": "word/3.docx", "chunk_id": 5,
  "parent_chunk_id": 5, "mini_chunk_index": 0,
  "content": "部署前需设置 DB2CODEPAGE=1208…", "blurb": "部署前需设…",
  "chunk_level": "mini", "is_mini_chunk": true, "is_large_chunk": false,
  "section_type": "text", "title": "i2Stream 部署指南",
  "large_chunk_id": 7, "doc_summary": "…", "chunk_context": "…",
  "keywords": ["DB2CODEPAGE=1208"], "data_types": ["config_param"] }
```

（mini1 无标注 → payload 里**没有** `keywords`/`data_types` 键——mini 不带空数组占位。）

#### 磁盘产物（`--embed` 输出目录）

```
output/
├── chunks.json        数组里第 5 项（18 个元数据字段，嵌入后另加 3 个；无正文、无向量本体、无 custom_payload）
├── chunk_005.txt      正文 + RAG 摘要/上下文 + 2 个 mini 全文（带 offsets 标注）
└── embeddings/
    ├── chunk_005_full.npy    (1024,)  ← 富化拼接文本
    ├── chunk_005_mini_0.npy  (1024,)
    ├── chunk_005_mini_1.npy  (1024,)
    └── chunk_005_title.npy   (1024,)  ← 与同文档其他块内容相同（缓存复用）
```

**一句话总结**：一个块 = 内存里**一个字段最全的对象** → 嵌入时**变 3 类文本各出一条向量** → 库里**炸成 1 主 + N 个 mini point**（主 point 胖、带全家福；mini point 瘦、只带自己和 parent 指针）→ 磁盘**1 行 json + 1 个 txt + 每向量 1 个 npy**。

### 1.2 其余 5 种 chunk_level 长什么样

先看全景对照，再逐个给关键字段实例（`standard` 全景见 §1.1）：

| chunk_level | 内存里有独立对象？ | 编码输入（1 个向量） | 与 standard 的核心差异 |
|---|---|---|---|
| `standard` | ✅ | 富化长文本（+各 mini 裸文本 + title） | §1.1 全家福 |
| `mini` | ❌ 只是父块的 `mini_chunk_texts[i]`，**Qdrant 里才成为独立 point** | 裸 mini 文本（≤600 字符） | 有 `parent_chunk_id` 回指；**不带** keywords/data_types 空占位 |
| `large` | ✅ | 富化长文本（4 块拼接后的整段） | `is_large_chunk=True`、双向指针、**永不带 mini** |
| `image` | ✅ | 富化长文本（OCR/描述或占位说明） | `image_file_id` 指向本地图片 |
| `tabular` | ✅ | 富化长文本（`Columns:` + `k=v` 行） | 表格**每行**一块，`section_type=tabular` |
| `log_pattern_standard` | ✅ | 富化长文本（`pattern.full_text()`） | **独立 collection** + 12 字段结构化 `custom_payload` |

---

#### `mini` — 唯一没有内存对象的层级

它不是 `DocAwareChunk`，只是父块身上的三份列表数据，入库时被展开成独立 point：

```python
# 父块（standard, chunk_id=5）身上：
mini_chunk_texts   = ["部署前需设置 DB2CODEPAGE=1208…", "监听端口 1521…"]
mini_chunk_offsets = [(812,1390), (1391,1985)]
mini_chunk_payloads = [{"keywords": [...]}, {}]     # [4.6] 逐个写

# Qdrant 里展开成 2 个 point（id = uuid5("mini_word/3.docx_5_0" / "_1")）：
{ chunk_level: "mini", is_mini_chunk: true,
  parent_chunk_id: 5, parent_document_id: "word/3.docx", mini_chunk_index: 0,
  content: "部署前需设置 DB2CODEPAGE=1208…",          # 裸文本，不套富化公式
  keywords: ["DB2CODEPAGE=1208"], ... }               # 来自 mini_chunk_payloads[0]；
                                                       # 无标注的 mini（index=1）没有此键
```

**检索含义**：mini 是"精准匹配层"——命中它后用 `parent_chunk_id` 反查父块，用 `mini_chunk_offsets[index]` 在父 content 里高亮。

---

#### `large` — ratio=4 个非 large 块拼成的上下文块

```python
DocAwareChunk(
    source_document = chunks[0].source_document,    # 继承首块的文档
    chunk_id  = 7,                                  # 入库时由 pipeline 续号（≥ 所有子块）
    content   = 块3 + "\n\n" + 块4 + "\n\n" + 块5 + "\n\n" + 块6,   # 逐块拼接 ≈ 8000 字
    blurb / title_prefix / metadata_suffix_* = 继承首块,
    chunk_level = "large",  is_large_chunk = True,
    large_chunk_id = 7,                             # 自指（= 自己的 chunk_id）
    large_chunk_reference_ids = [3, 4, 5, 6],       # 指回组内子块 ★核心字段
    mini_chunk_texts = None,                        # 永不带 mini（Embedder 违反即 RuntimeError）
    image_file_id = None,
)
```

反向：被合并的 4 个子块各自 `large_chunk_id=7`、`large_chunk_reference_ids=[]` —— **双向指针构成父子关系**。
组里只剩 1 个块时不合并（不会产生只有一个子的 large）。`[4.6]` 富化对拼接后的 content 再检测，所以 large 的 `keywords` ≈ 组内子块标注的并集。

> `section_type` 恒为 `text`（即使子块全是图片块），`image_file_id` 恒为 `null` —— 这是刻意设计，理由与"勿改"清单见 **§2.1**。

---

#### `image` — 每张提取图片一块

```python
DocAwareChunk(
    content  = "图表显示 i2Stream 与 Oracle 的同步链路…",   # 图片处理开: OCR/Vision 描述
               # 或 "[嵌入图片: arch.png]"                  # 图片处理关: 占位说明
    blurb    = content[:100] 或 "[Image]",
    section_type = SectionType.IMAGE,
    chunk_level  = "image",
    image_file_id = "output/images/image_000_arch.png",    # ★核心字段，本地图片路径
    mini_chunk_texts = None,                               # 不切 mini
)
```

来源：提取器抽出的内嵌图片，按正文里 `【PIC:n】` 占位符与文本**交错**成 Section；此处 `section_type=image` 与 `chunk_level=image` 同值（注意 `section_type` 是内容形态、`chunk_level` 是层级，两者正交）。

---

#### `tabular` — 表格每一行一块

```python
# 原表格 3 行数据 → 3 个 tabular 块，chunk_id 连续
DocAwareChunk(
    content  = "部署清单\nColumns: 节点, 端口, 状态\n节点=node1, 端口=1521, 状态=正常",
               # ↑ heading（可选） + 列头 + 本行 k=v（空值列省略）
    blurb    = "节点=node1, 端口=1521, 状态=正常"[:100],
    section_type = SectionType.TABULAR,
    chunk_level  = "tabular",
    section_continuation = (i > 0),        # 第 0 行之后都算续接
    mini_chunk_texts = None,               # 不切 mini
)
```

来源：`utils.detect_and_parse_table()` 启发式从正文抠出表格 → CSV 化为一个 `TABULAR` Section，同时把表格行从普通文本里删掉防重复。

---

#### `log_pattern_standard` — 日志模式库专用（独立 collection）

```python
DocAwareChunk(
    source_document = Document(id="log_pattern_{prefix}_P001", source="LOG_PATTERN",
                               title="P001", sections=[Section(TEXT, pattern.full_text())]),
    content  = pattern.full_text(),                # 模式描述全文
    blurb    = pattern.fingerprint_text[:150],
    chunk_level = "log_pattern_standard",          # ★第 6 个枚举值
    mini_chunk_texts   = pattern.mini_texts(),     # 2~4 条（指纹/样本粒度）
    mini_chunk_offsets = [],                       # 无偏移（非文本切分而来）
    custom_payload = {                             # ★12 字段结构化，见 §6.3-B
        "is_log_pattern": True, "pattern_id": "P001",
        "log_fingerprint": ["IAERR_LOG_SEQ", "4002"],   # string[] 保持数组
        "component": "i2Stream", "severity": "ERROR",
        "error_codes": ["-4002"], "db_types": ["Oracle"],
        "keywords": ["IAERR_LOG_SEQ", "4002"],          # = log_fingerprint，复用兜底
        "source_note": "...", "updated_at": "...", "chunk_type": "standard",
    },
    mini_chunk_payloads = [同上 ×N, chunk_type="mini", + mini_content_preview],  # 逐 mini
)
# 写入 log_patterns_collection —— 禁止混入文档 collection
```

---

---

## 2. chunk_level 类型总表

`chunk_level` 实际有 **6 个枚举值**（`models.py:61` 注释列出 5 个，`log_patterns/chunker.py` 又使用了第 6 个）：

| chunk_level | 产生者 | 是否独立向量点 | 关键特征字段 | 所属 collection |
|---|---|---|---|---|
| `standard` | `chunking/text.py: chunk_text_sections()` — chonkie `SentenceChunker`，512 token（×4=2048 字符）切分，overlap=0 | 是（主 point） | `mini_chunk_texts` / `mini_chunk_offsets` / `title_prefix` / `section_continuation` | 文档 collection（如 `i2stream_collection`） |
| `mini` | `qdrant_store.upsert_chunks()` 从 standard 的 `mini_chunk_texts` 逐条展开，每条 150 token（×4=600 字符） | 是（独立 mini point） | `parent_chunk_id`、`parent_document_id`、`mini_chunk_index`、`is_mini_chunk=True` | 同上 |
| `large` | `chunking/large.py: generate_large_chunks()` — 每 `ratio=4` 个非 large chunk 合并（组内仅 1 个则不合并） | 是（主 point） | `is_large_chunk=True`、`large_chunk_reference_ids`、`large_chunk_id`（= 自身 chunk_id 自指）；**不含** mini | 同上 |
| `image` | `chunking/image.py: chunk_image_section()` — 每张提取图片 1 块 | 是（主 point） | `section_type=image`、`image_file_id`（本地图片路径） | 同上 |
| `tabular` | `chunking/tabular.py: chunk_tabular_section()` — 表格**每行** 1 块 | 是（主 point） | `section_type=tabular`；content = 表头 + `k=v` 行（可带 heading） | 同上 |
| `log_pattern_standard` | `log_patterns/chunker.py: LogPatternChunker.chunk()` — 每条日志模式 1 块 + 2~4 个 mini | 是（主 point） | `custom_payload` 结构化 12 字段（见 §6.3）；mini 的 `chunk_level` 仍为 `"mini"` | `log_patterns_collection`（独立，禁止混入文档 collection） |

**父子/双向指针关系**：

- mini → standard：`parent_chunk_id`（payload 层）
- standard → large：`large_chunk_id`（组内每个子块指向 large 的 chunk_id）
- large → standard：`large_chunk_reference_ids`（large 指回组内所有子块）
- 约束：**large chunk 永不携带 mini**（`Embedder.embed_chunks` 遇到违反抛 `RuntimeError`）

> 注：`chunking/large.py:51` 注释写"只取文本+表格"，实际代码 `eligible = [c for c in chunks if not c.is_large_chunk]` 包含图片块——以代码为准，注释已过时。

### 2.1 大块 `section_type` 恒为 `text`（刻意设计，勿改）

**现象**：即使一个大块 100% 由图片块组成，它的 `section_type` 也是 `text`。

**机制**：`chunking/large.py: _combine_chunks()` 构造 `DocAwareChunk` 时**不传** `section_type`，因此走 `models.py:53` 的默认值 `SectionType.TEXT`；同一处 `large.py:16` 显式置 `image_file_id=None`。

**为什么这是正确的**（而非缺陷）：

- 图片处理（本地 OCR / 远程 Vision）的产物**本身就是文本**，由 `chunking/image.py` 放进 `content`。实测内容形如 `[图片: image33.png]\n[图片内容] 这是一张…截图…\n[图片文字] [ERROR]…`，编码进向量的就是这段文本，语义检索不受影响。
- `models.py:19-25` 的 `Section.IMAGE` 本就同时携带 `text`（OCR/Vision 输出）与 `image_file_id` —— **`section_type` 标的是内容来源，不是字符形态**。按此约定，图片描述组成的大块标 `image` 反而才是不一致的。
- 一个大块可能含多张图（实测有含 4 张的），单值 `image_file_id` 表达不了，`null` 是它唯一诚实的取值。

**实测基线**（2026-09-21 全量统计 `i2stream_collection`，2546 点）：

| 指标 | 数值 |
|---|---|
| 大块总数 | 256 |
| ├ 纯图片块组成 | 167（65%） |
| ├ 纯文本块组成 | 79（30%） |
| └ 文本 + 图片混合 | 10（3%） |
| 大块 `section_type` 为 `text` | **256 / 256（100%）** |
| 图片块被并入大块 | 675 / 677（99%） |

> 测量方式：Qdrant `POST /collections/<name>/points/scroll` 取全量 payload，按 `large_chunk_reference_ids` 反查子块的 `section_type`。
> **勿引用 `docs/qdrant-data-audit.md`（2026-07-20）的相关数字**——那是图片处理接入**之前**的快照（当时图片块 content 是 `[嵌入图片: xxx.png]` 占位符，且用 `is_mini_chunk=True` 标记标准块），与当前状态无关。2026-09-21 实测含旧占位符的大块只剩 6/256（2%）。

**已知且已接受的后果**（2026-09-21 确认，非缺陷）：

- 按 `section_type` 过滤时，大块无法与纯文本块区分；
- `vector_store/searcher.py:20-35` 的 `RetrievalResult` 没有 `image_file_id` 字段，原图路径对**任何** chunk 都取不到（不只大块）；
- `docs/query/chunk-aware-search-strategy.md` §2.3 提到"可返回 `image_file_id` 供前端展示原图"，属**未采纳的设想**——已确认 i2Agent / 前端无此需求，纯文本检索即可。

**不要改**（本节核心价值，以下三条均已验证）：

1. **不要**把大块的 `section_type` 改成 `image`，也不要为此新增 `SectionType.MIXED` + `child_section_types` / `image_file_ids` payload 字段。该方案曾完整评估，因无消费需求而放弃。
2. **不要**"统一" `vector_store/searcher.py:152` 的硬编码 `"text"`。该分支（`:136-160`）返回的是**父大块**的 `content` / `chunk_id` / `is_large_chunk=True`，此处字面量描述的是父块，与 256/256 父块 payload 一致。改成读子块 payload，会拿子块类型去标父块内容，**反而引入不一致**。同文件 `:125` / `:172` / `:281` 处理的是"结果即自己"的情形，读 payload 是对的——两类分支本就应当不同。
3. **不要**把 `chunking/large.py:51` 改成像其注释那样过滤掉图片块。那会改变大块组成，属行为变更而非注释修正（差异已在 §2 末尾的注中记录）。

---

## 3. DocAwareChunk 全字段参数表

定义：`models.py:48-72`。数据类原地修改。

### 3.1 身份与内容

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `source_document` | `Document` | 必填 | 所属文档对象（id/title/metadata 等） | 分块器 |
| `chunk_id` | `int` | 必填 | 文档内全局序号；文本→图片→表格→large 顺序连续编号，跨文档可重复 | pipeline 各阶段续号 |
| `content` | `str` | 必填 | 完整正文。嵌入时参与富化拼接（§5），也是 payload 的 `content` | 分块器；large 合并追加 |
| `blurb` | `str` | 必填 | 摘要（`extract_blurb` 取前 150 字符），规则版 contextual RAG 取相邻块 blurb 作上下文 | 分块器 |

### 3.2 类型与定位

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `section_type` | `SectionType` | `TEXT` | `text` / `image` / `tabular`（内容形态，与 `chunk_level` 正交：image 块两者都是 image，mini point 沿用父块值） | 分块器 |
| `chunk_level` | `str` | `"standard"` | 层级枚举，见 §2 六值 | 分块器 / large / 日志模式分块器 |
| `image_file_id` | `str \| None` | `None` | 图片块关联的本地文件路径（`output/images/...`） | `chunking/image.py` |
| `section_continuation` | `bool` | `False` | 该块起始位置不是文档/段落开头（文本块 `idx>0` 即为 True；表格行 `i>0`） | 分块器 |
| `is_large_chunk` | `bool` | `False` | 是否大块；检索聚合时据此归并 | `chunking/large.py` |

### 3.3 嵌入增强文本（不入 payload，只参与嵌入拼接）

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `title_prefix` | `str` | `""` | `"{文档标题}\n"`，拼在嵌入文本最前，提升标题匹配 | `chunking/text.py` |
| `metadata_suffix_semantic` | `str` | `""` | 语义后缀，拼在嵌入文本最后；当前文档管线不写，large 合并时继承首块（即恒空） | 预留 |
| `metadata_suffix_keyword` | `str` | `""` | 关键词后缀；同上，预留 | 预留 |
| `doc_summary` | `str` | `""` | 文档级摘要（Contextual RAG，LLM 或规则版取前 300 字符），拼在 content **前** | `contextual_rag.py` |
| `chunk_context` | `str` | `""` | 位置上下文 `"Previous: ...; Next: ..."`，拼在 content **后** | `contextual_rag.py` |
| `contextual_rag_reserved_tokens` | `int` | `0` | 为 Contextual RAG 预留的 token 配额；**当前无代码读写，纯占位** | — |

### 3.4 大块指针

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `large_chunk_id` | `int \| None` | `None` | 子块 → 所属 large 的 chunk_id（large 块自身 = 自身 chunk_id，自指） | `chunking/large.py` 双向写 |
| `large_chunk_reference_ids` | `list[int]` | `[]` | large → 组内子标准块 chunk_id 列表；子块上恒为 `[]` | `chunking/large.py` |

### 3.5 mini-chunk

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `mini_chunk_texts` | `list[str] \| None` | `None` | 细粒度子块文本列表（150 token 级）；large/image/tabular 恒为 None | `chunking/text.py`、日志模式分块器 |
| `mini_chunk_offsets` | `list[tuple[int,int]] \| None` | `None` | 每个 mini 在**父 content** 中的 `(start, end)` 字符偏移，顺序查找定位；用于命中回源高亮。日志模式分块器传 `[]`（无偏移） | `chunking/text.py: split_mini_chunks()` |

### 3.6 结构化扩展（payload 通路）

| 字段 | 类型 | 默认 | 含义 | 写入方 |
|---|---|---|---|---|
| `custom_payload` | `dict` | `{}` | 合并进主 point payload 的任意键值。两套既有使用：富化 `keywords`/`data_types`（pipeline `[4.6]`）；日志模式结构化 12 字段（`log_patterns/payload.py`） | `[4.6]`、`LogPatternChunker` |
| `mini_chunk_payloads` | `list[dict] \| None` | `None` | 与 `mini_chunk_texts` 下标对齐的逐 mini payload；无标注的 mini 为 `{}` | `[4.6]`、`LogPatternChunker` |

### 3.7 遗留/低频字段

| 字段 | 类型 | 默认 | 含义 | 现状 |
|---|---|---|---|---|
| `source_links` | `dict[int, str] \| None` | `None` | 位置→链接映射（设计源自 Onyx HTML 链接追踪） | 文档管线不写；large 合并时兜底 `{0: ""}`，实际恒空 |

---

## 4. IndexChunk / ChunkEmbedding

`models.py:76-88`。`IndexChunk` **继承** `DocAwareChunk`（嵌入阶段用 `dataclasses.fields(DocAwareChunk)` 全字段拷贝构造，因此 `custom_payload` 等全部保留），追加两个向量字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `embeddings` | `ChunkEmbedding` | 见下 |
| `title_embedding` | `list[float] \| None` | 文档标题向量。**按文档去重缓存**：同一文档的所有 chunk 复用同一个 title 向量，只编码一次 |

`ChunkEmbedding`：

| 字段 | 含义 |
|---|---|
| `full_embedding` | 主向量 — 编码对象是**富化文本**（§5 公式），不是裸 content |
| `mini_chunk_embeddings` | 与 `mini_chunk_texts` 一一对应的子向量，编码对象是裸 mini 文本 |

批量编码的扁平顺序：`[chunk1 富化文本, chunk1_mini0, chunk1_mini1, ..., chunk2 富化文本, ...]`（`embedding/embedder.py`）。

---

## 5. 嵌入富化文本组合公式

`embedding/base.py: generate_enriched_content_for_chunk_embedding()`

```
嵌入输入 = title_prefix + doc_summary + content + chunk_context + metadata_suffix_semantic
           └─标题─┘   └─RAG摘要─┘  └正文┘   └─RAG位置上下文─┘   └─语义后缀(恒空)┘
```

- mini 向量不套此公式，直接编码 `mini_chunk_texts[i]` 裸文本
- title 向量单独编码 `document.title`
- 预富化 `[4.5]` 追加的标注块是 `content` 的一部分，因此**主向量天然包含标注文本**（BGE 语义锚点），`[4.6]` 的 payload `keywords` 是同一信息的结构化镜像

---

## 6. Qdrant payload 字段表

`vector_store/qdrant_store.py: upsert_chunks()`

### 6.1 主 point（每个 standard/large/image/tabular/log_pattern_standard 一个）

| 字段 | 类型 | 说明 |
|---|---|---|
| `document_id` | str | 源文档 id（= 文件路径 / `log_pattern_{prefix}_{id}`） |
| `chunk_id` | int | 文档内序号 |
| `content` | str | 完整正文 |
| `blurb` | str | 前 150 字摘要 |
| `section_type` | str | `text` / `image` / `tabular`；**大块恒为 `text`**，见 §2.1 |
| `title` | str \| null | 文档标题 |
| `is_large_chunk` | bool | 是否大块 |
| `chunk_level` | str | 层级（§2 六值） |
| `large_chunk_reference_ids` | list[int] | 仅 large 非空 |
| `large_chunk_id` | int \| null | 子块指向的 large；large 为自指 |
| `doc_summary` / `chunk_context` | str | Contextual RAG 文本 |
| `mini_chunk_count` | int | mini 数量 |
| `mini_chunk_texts` | list[str] | mini 全文列表（冗余存储，便于直接读取） |
| `mini_chunk_offsets` | list[[int,int]] | mini 在 content 中偏移 |
| `is_mini_chunk` | bool | 主 point 恒 `False` |
| `image_file_id` | str \| null | 图片路径；**大块恒为 `null`**（子块可含多图，单值表达不了），见 §2.1 |
| `keywords` | list[str] | 默认 `[]`；富化 `[4.6]` 覆盖为标注词（如 `错误码 -4002 (IAERR_LOG_SEQ)`） |
| `data_types` | list[str] | 默认 `[]`；富化覆盖为类型名（8 枚举见 6.3 下） |
| `title_embedding` | list[float] | 仅当有 title 向量时写入 |
| `mini_chunk_embeddings` | list[list[float]] | 仅当有 mini 向量时写入（冗余，主 point 内嵌子向量） |
| **+ `payload.update(custom_payload)`** | — | 富化/日志模式的结构化字段在此合并覆盖 |

### 6.2 mini point（每个 mini 文本一个，独立向量）

| 字段 | 说明 |
|---|---|
| `document_id` / `chunk_id` / `parent_document_id` / `parent_chunk_id` | 父子定位（`chunk_id` 与 `parent_chunk_id` 同值 = 父块序号） |
| `mini_chunk_index` | 在父块内的 mini 序号（0 起） |
| `content` / `blurb` | mini 裸文本 / 前 150 字 |
| `section_type` / `title` | 沿用父块 |
| `is_large_chunk=False` / `chunk_level="mini"` / `is_mini_chunk=True` | 层级标识 |
| `large_chunk_id` / `doc_summary` / `chunk_context` | 沿用父块 |
| **+ `payload.update(mini_chunk_payloads[i])`** | 逐 mini 结构化字段（富化 / 日志模式），无则不合并 |

mini point **不写** `keywords`/`data_types` 默认占位——字段仅在 `mini_chunk_payloads[i]` 提供时存在。

### 6.3 `custom_payload` 两套既有 schema

**A. 富化（pipeline `[4.6]`，`enable_enrichment=True` 时按块内容检测）**

| 键 | 值示例 | 说明 |
|---|---|---|
| `keywords` | `["错误码 -4002 (IAERR_LOG_SEQ)", "Oracle 19c", "1521"]` | 富化标注词（`Annotation.enriched`），供 `hybrid_search` 关键词兜底子串匹配 |
| `data_types` | `["error_code", "database", "port"]` | 检测器类型名去重排序。8 个枚举：`error_code`、`version`、`database`、`port`、`config_param`、`uuid`、`ip`、`filepath` |

**B. 日志模式（`log_patterns/payload.py: build_pattern_payload()`）**

| 键 | 说明 |
|---|---|
| `is_log_pattern=True` | 标识位 |
| `pattern_id` | 模式 ID |
| `log_fingerprint` | 模板指纹（`string[]`，必须保持数组类型） |
| `component` / `severity` | 组件 / 级别 |
| `error_codes` / `db_types` | 错误码列表 / 数据库类型列表 |
| `keywords` | **= `log_fingerprint`**（复用 keywords 兜底通路） |
| `source_note` / `updated_at` | 来源备注 / 更新时间 |
| `chunk_type` | `"standard"` 或 `"mini"`（mini 另带 `mini_content_preview` 前 100 字） |

### 6.4 payload 索引现状

`_ensure_payload_indexes()` 当前只建 3 个（collection 首次创建时）：

| 字段 | schema | 状态 |
|---|---|---|
| `keywords` | keyword | ✅ 已建（兜底匹配） |
| `data_types` | keyword | ✅ 已建（类型过滤） |
| `content` | text | ✅ 已建（全文兜底） |

`chunk_level`、`section_type`、`document_id`、`parent_chunk_id`、`large_chunk_id` 等**均未建索引**（可过滤但走全量扫描），详见 `docs/query/chunk-aware-search-strategy.md` §4.1 优先级。

---

## 7. chunks.json 落盘字段表

`utils.py: save_results()` 输出（`--embed` 时另存 `.npy` 向量文件）：

| 字段 | 说明 |
|---|---|
| `chunk_id` / `section_type` / `chunk_level` / `blurb` | 基本标识 |
| `content_length` | 正文长度（**不存正文本身**，正文在 `chunk_xxx.txt`） |
| `title_prefix` / `section_continuation` | 嵌入前缀 / 是否续接 |
| `is_large_chunk` / `large_chunk_id` / `large_chunk_reference_ids` | 大块关系 |
| `mini_chunk_count` / `mini_chunk_texts` / `mini_chunk_offsets` | mini 三件套 |
| `doc_summary` / `chunk_context` | Contextual RAG 输出 |
| `image_file_id` | 图片路径 |
| `source_document_id` / `source_document_title` | 源文档 |
| `embedding_dim` / `has_full_embedding` / `mini_embedding_count` | 仅嵌入后：维度与数量（向量本体在 `embeddings/chunk_xxx.npy`） |

> `custom_payload`（keywords/data_types）**不写入 chunks.json**，只进 Qdrant payload。

---

## 8. 附录

### 8.1 Section 输入类型（`models.py:13-25`）

| SectionType | 来源 | 携带字段 |
|---|---|---|
| `TEXT` | 各提取器正文段落（按空行切分）+ `[4.5]` 富化标注块 | `text`、`heading`、`link` |
| `IMAGE` | 提取器内嵌图片（`【PIC:n】` 占位符与正文交错） | `text`（OCR/Vision 描述或占位说明）、`image_file_id` |
| `TABULAR` | `utils.detect_and_parse_table()` 启发式检测的表格（CSV 化） | `text`（CSV）、`heading` |

### 8.2 死代码：`chunking/log.py`

`LogChunker` / `LogEntry` / `LogChunk`（以 Drain 模板为单元的日志分块器）**全项目无任何 import 与调用**（`chunking/__init__.py` 未导出、`pipeline.py` 未引用），功能上被 `log_patterns/` 链路取代。其结构（`template_id`、`template`、`log_level`、`related_template_ids` 等）**不进入** `DocAwareChunk` / Qdrant，仅作历史遗留记录，勿与 §2 的 `log_pattern_standard` 混淆。

### 8.3 快速对照：找字段去哪看

| 想查 | 位置 |
|---|---|
| **一个块到底长什么样** | **§1.1 standard 三副面孔全景 + §1.2 其余 5 种 chunk_level 实例** |
| 内存块结构定义 | `models.py` |
| 各类型怎么生成 | `chunking/{text,image,tabular,large}.py`、`log_patterns/chunker.py` |
| payload 怎么落盘 | `vector_store/qdrant_store.py: upsert_chunks()` |
| 嵌入拼了什么 | `embedding/base.py` + `embedding/embedder.py` |
| 富化写什么 | `enrichment.py` + `pipeline.py [4.5]/[4.6]` |
| 磁盘输出 | `utils.py: save_results()` |
| 检索怎么用这些字段 | `vector_store/searcher.py`、`docs/query/chunk-aware-search-strategy.md` |
