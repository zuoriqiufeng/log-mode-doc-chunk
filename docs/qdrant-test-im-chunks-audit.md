# test_im_chunks Qdrant 数据实测报告

> 日期: 2026-07-21 | 来源: 对 `test_im_chunks` 全量扫描
> 文档: 崖山部署.md、AI,DB2,AS400错误排查c.docx

---

## 1. 总体分布

| chunk_level | 数量 | 占比 | section_type |
|-------------|-----:|------:|-------------|
| `mini` | 60 | 52.6% | text |
| `standard` | 16 | 14.0% | text |
| `image` | 27 | 23.7% | image |
| `large` | 11 | 9.6% | text |
| **总计** | **114** | | |

---

## 2. 按文档拆分

### 2.1 崖山部署.md

| chunk_level | 数量 |
|-------------|-----:|
| standard | 8 |
| mini | 31 |
| large | 2 |
| **小计** | **41** |

### 2.2 AI,DB2,AS400错误排查c.docx

| chunk_level | 数量 |
|-------------|-----:|
| standard | 8 |
| mini | 29 |
| image | 27 |
| large | 9 |
| **小计** | **73** |

**说明**: docx 经改进后，27 张内嵌图片已全部独立为 `chunk_level=image` 的 chunk。

---

## 3. standard 块 mini_chunk 分布

| mini_chunk_count | standard 块数 |
|-----------------:|--------------:|
| 1 | 1 |
| 3 | 1 |
| 4 | 14 |
| **合计** | **16** |

**结论**: 当前所有 standard 块均携带 mini chunks，不存在空 mini 的标准块。

---

## 4. large chunk 父子关联

### 4.1 Markdown 文档

```
large chunk_id=9, refs=[4, 5, 6, 7]
```

### 4.2 DOCX 文档

```
large chunk_id=35, refs=[0, 1, 2, 3]
large chunk_id=39, refs=[16, 17, 18, 19]
large chunk_id=41, refs=[24, 25, 26, 27]
large chunk_id=43, refs=[32, 33, 34]
```

**结论**: large chunk 引用关系正确，无图片占位符污染。

---

## 5. image chunk 状态

| 字段 | 状态 |
|------|------|
| `section_type` | image |
| `chunk_level` | image |
| `content` | `[嵌入图片: imageX.png]`（未开启图片处理时） |
| `image_file_id` | 本地图片路径 |

**说明**: 当前未开启有效图片处理后端，image chunk 内容为占位符；`image_file_id` 已写入 payload，前端可据此展示原图。

---

## 6. 关键字段覆盖

| 字段 | 覆盖率 | 说明 |
|------|:------:|------|
| `chunk_id` | 100% | 文档内唯一 |
| `chunk_level` | 100% | standard/mini/image/large |
| `section_type` | 100% | text/image |
| `mini_chunk_count` | 100% standard | standard 块均有 |
| `mini_chunk_offsets` | 100% standard | 子块偏移完整 |
| `large_chunk_id` | 100% standard/mini | 指向父 large |
| `large_chunk_reference_ids` | 100% large | 子块引用完整 |
| `image_file_id` | 100% image | 图片路径完整 |
| `document_id` | 100% | 源文档路径 |

---

## 7. 对查询策略的影响

见 `docs/query/chunk-aware-search-strategy.md`。

核心结论：
- `large` 块内容正常，可作为上下文扩展层。
- `image` 块已独立，支持图片原图展示和多模态检索。
- `mini` 块有独立向量点和精确偏移，适合作为默认精准检索入口。
