# i2stream_collection Qdrant 数据实测报告

> 日期: 2026-07-20 | 来源: 对 `i2stream_collection` 全量扫描
>
> 目的: 验证 chunk 项目的分块逻辑（INTRODUCTION.md §5）在 Qdrant 中的实际落盘状态

---

## 1. 总体分布

| 类型 | 数量 | 占比 | section_type |
|------|:---:|------|-------------|
| 大块 (`is_large_chunk=True`) | 188 | 10.6% | 全部 text |
| 标准块 (`is_mini_chunk=True`) | 837 | 47.1% | 全部 text |
| 非分块 (`both False`) | 752 | 42.3% | text + image |
| **总计** | **1777** | | |

---

## 2. content 长度分布

| 类型 | median | min | max | 说明 |
|------|:---:|:---:|:---:|------|
| 标准块 | 548 字符 | 68 | 598 | 远小于设计的 512 tokens（~2048 字符），约为 137 tokens |
| 大块 | 138 字符 | 133 | 8137 | 两极分化严重（见 §3） |
| 非分块 | — | 647 | 2032 | 长文本为主，部分乱码 |

### 2.1 大块 content 内容质量

| 分类 | 数量 | 占比 | 说明 |
|------|:---:|------|------|
| 图片占位符 | 144 | 76.6% | content 为 `[嵌入图片: xxx.png]` 拼接，全部被 `_is_valid_content` 过滤 |
| 真实文本 | 44 | 23.4% | 8000+ 字符的真实文档内容，质量好 |

**大块 label 全部为 `section_type=text`**，即使是图片占位符内容。

---

## 3. mini_chunk_texts 分布

| 类型 | 总数 | 非空 | 非空率 | 非空点典型结构 |
|------|:---:|:---:|:---:|------|
| 标准块 | 837 | **0** | 0% | — |
| 大块 | 188 | **0** | 0% | — |
| 非分块 | 752 | **224** | 29.8% | section_type=text, large_chunk_id 有效, mini_chunk_count=2~4 |

### 3.1 非分块长文本结构详解

这 224 个点（全部 `section_type=text`）具有完整、一致的内部结构：

```
content = mt[0] + mt[1] + mt[2] + ... + mt[n-1]   (无分隔符，精确拼接)
```

**字段覆盖率（224 个点）**：

| 字段 | 覆盖率 | 说明 |
|------|:---:|------|
| `content`, `blurb`, `chunk_id`, `section_type` | 100% | 基础字段 |
| `mini_chunk_texts`, `mini_chunk_count`, `mini_chunk_embeddings` | 100% | 子块文本 + 子块向量，均完整 |
| `chunk_context` | 100% | Previous/Next 上下文 |
| `doc_summary`, `title`, `title_embedding` | 100% | 文档摘要 + 标题 + 标题向量 |
| `large_chunk_id` | 99% | 指向父大块 |
| `is_large_chunk`, `is_mini_chunk` | 100% | 均为 `False` |

**数值统计**：

| 指标 | min | max | median | mean |
|------|:---:|:---:|:---:|:---:|
| content 长度 | 68 | 11455 | **2016** | 1904 |
| mini_chunk_texts 数量 | 1 | 5 | **4** | 3.7 |
| 子块长度 | 45 | 11455 | **563** | 510 |
| mini_chunk_count | 1 | 5 | 4 | 3.7 |
| large_chunk_id | 5 | 287 | 149 | — (53 unique) |

### 3.2 完整范例

```
chunk_id=30, large_chunk_id=276, section_type=text
mini_chunk_count=4

content (2001 字符):
  = mt[0] (586 chars)    → "备端数据库,备端数据库...映射方式,非整库映射,库映射,添加..."
  + mt[1] (591 chars)    → "库名、表名、列名的输入区分大小写...表映射表名支持正则表达式..."
  + mt[2] (571 chars)    → "映射方式,非整库映射,表映射,添加字段映射..."
  + mt[3] (253 chars)    → "是否全同步,是否全同步...全量同步数据源..."

  验证: content == "".join(mt) = True

chunk_context:
  Previous: "3.字符类型支持逻辑判断字符>、=..."
  Next: "全量导出线程数,全量导出线程数,..."

doc_summary:
  "i2Stream 9.1.4 Beta界面操作手册\n版权所有 © 上海英方软件股份有限公司..."

title: "4303d385-f306-4cb1-b0a3-843e3e54c9be.docx"
```

### 3.3 与设计文档的对比

| 属性 | 设计 (INTRODUCTION.md) | 实测 |
|------|------|------|
| 定位 | 标准块含 mini_chunk_texts | 非分块长文本含 mini_chunk_texts |
| content 与 mt 关系 | content 为独立文本，mt 为子切分 | **content == mt 精确拼接** (224/224) |
| 子块粒度 | 150 tokens (~600 字符) | ~510 字符 (~127 tokens) |
| 子块数量 | 未明确 | 2~5，中位数 4 |
| mini_chunk_embeddings | 应有独立向量 | ✅ 100% 存在 |
| chunk_context | 应有 | ✅ 100% 存在 |
| doc_summary | 应有 | ✅ 100% 存在 |

### 3.4 结构推理

这 224 个点实际上是 chunk 管线的 **"正确产物"**：它们走的是完整流程（文本提取 → 分块 → 子块切分 → Contextual RAG → 双向量嵌入），但**没有被标记为 `is_mini_chunk=True`**。可能原因：

1. 它们是 chunking/text.py 的输出，但 `is_mini_chunk` 标记在入库 Qdrant 时遗漏
2. 或者 pipeline 中对 "大文档" 走了一条不同的路径（不分标准块，直接子块切分）
3. 数据来源：53 个 unique `large_chunk_id`，每个 large_chunk_id 对应 4~14 个这类点，集中在少量文档中

这 224 个点是目前 Qdrant 中**唯一同时拥有完整 content + mini_chunk_texts + mini_chunk_embeddings** 的数据，是子块级精准检索的唯一可行入口。

---

## 4. 父子关联验证

### 4.1 文本大块（正常）

```
大块 large_chunk_id=155, ref_ids=[40,41,42,43]
  ├── chunk_id=40 [text] → GRANT SELECT ON oceanbase... (标准块)
  ├── chunk_id=41 [text] → TDSQL、GoldenDB最小权限... (标准块)
  ├── chunk_id=42 [text] → GRANT SELECT ON DBA_USERS... (标准块)
  └── chunk_id=43 [text] → gsql -d postgres -p 36000... (标准块)

关联验证: ✓ 全部匹配
标准块数量: 16（含跨文档重复 chunk_id）
```

### 4.2 图片大块（占 76.6%）

```
大块 large_chunk_id=26, ref_ids=[12,13,14,15]  (section_type=text)
  ├── chunk_id=12 [image] → [嵌入图片: page_2_image_Im14.png]
  ├── chunk_id=13 [image] → [嵌入图片: page_2_image_Im15.png]
  ├── chunk_id=14 [image] → [嵌入图片: page_2_image_Im16.png]
  └── chunk_id=15 [image] → [嵌入图片: page_2_image_Im2.png]

关键发现:
  - 4 个子块全部是 section_type=image, is_mini_chunk=False
  - 大块自身被标记为 section_type=text
  - Multipass 合并时未过滤 image 类型
```

---

## 5. 与设计文档的偏差

| 设计 (INTRODUCTION.md §5) | 实测 | 偏差程度 |
|------|------|:---:|
| 标准块 512 tokens (2048 字符) | median 548 字符 (~137 tokens) | 3.7× 偏差 |
| 标准块含 mini_chunk_texts (150-token 子块) | 0/837 有 mini_chunk_texts | 100% 缺失 |
| 大块 = 4 个标准块拼接 | 大块 ref_ids 正确，但 76.6% 拼接的是 image chunk | 内容污染 |
| 大块优先匹配策略 | 不可行（76.6% 被 `_is_valid_content` 过滤） | 策略失效 |
| mini_chunk_texts 在标准块中 | 实际在 224 个非分块长文本中 | 位置偏差 |

---

## 6. 对检索增强方案的影响

见 i2stream-bkn 项目《chunk-aware 检索增强》(doc/chunk-aware-search-enhancement.md)

核心修正：
- `large_first` 策略不可行（大块 76.6% 无效）
- `parent_expand` 作为首期推荐（标准块主力 + doc_summary 增强）
- 224 个非分块长文本的 mini_chunk_texts 可作为后续增强维度
