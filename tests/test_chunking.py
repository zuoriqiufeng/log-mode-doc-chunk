"""分块测试：mini-chunk 偏移、文本分块、大 chunk 合并。

覆盖三条硬约束：
1. mini-chunk 偏移必须能精确映射回原 chunk 文本；
2. 大 chunk 绝不能携带 mini-chunk（`Embedder` 会抛 RuntimeError 拦截）；
3. 只有被合并的标准 chunk 才设置 `large_chunk_id`。
"""

from __future__ import annotations

import pytest

from chunking.large import generate_large_chunks
from chunking.text import (
    chunk_text_sections,
    get_mini_chunk_texts,
    split_mini_chunks,
)
from models import DocAwareChunk, Document, Section, SectionType


def _make_document(sections: list[Section], title: str | None = "文档标题") -> Document:
    return Document(
        id="doc-1",
        semantic_identifier="doc-1",
        sections=sections,
        title=title,
    )


def _make_text_chunk(chunk_id: int, content: str = "content", mini: list[str] | None = None) -> DocAwareChunk:
    return DocAwareChunk(
        source_document=_make_document([]),
        chunk_id=chunk_id,
        content=content,
        blurb=content[:150],
        mini_chunk_texts=mini,
    )


@pytest.fixture(scope="module")
def mini_splitter():
    """与 chunk_text_sections 内部一致的 mini-chunk 切分器。"""
    from chonkie import SentenceChunker

    return SentenceChunker(
        tokenizer="character", chunk_size=600, chunk_overlap=0, approximate=True
    )


LONG_TEXT = "\n\n".join(
    f"第 {i} 段：这是一段用于测试分块行为的中文文本，包含足够长度以触发切分逻辑。"
    for i in range(40)
)


class TestSplitMiniChunks:
    def test_offsets_map_back_to_source_text(self, mini_splitter):
        """核心不变量：chunk_text[start:end] 必须等于对应的 mini-chunk 文本。"""
        result = split_mini_chunks(LONG_TEXT, mini_splitter)

        assert result is not None
        texts, offsets = result
        assert len(texts) == len(offsets) >= 1
        for text, (start, end) in zip(texts, offsets):
            assert LONG_TEXT[start:end] == text

    def test_offsets_are_monotonic(self, mini_splitter):
        texts, offsets = split_mini_chunks(LONG_TEXT, mini_splitter)
        assert offsets == sorted(offsets)
        # 相邻块不重叠
        for (_, prev_end), (next_start, _) in zip(offsets, offsets[1:]):
            assert next_start >= prev_end

    def test_empty_text_returns_none(self, mini_splitter):
        assert split_mini_chunks("   \n  ", mini_splitter) is None

    def test_missing_splitter_returns_none(self):
        assert split_mini_chunks(LONG_TEXT, None) is None

    def test_get_mini_chunk_texts_matches_split_result(self, mini_splitter):
        assert get_mini_chunk_texts(LONG_TEXT, mini_splitter) == split_mini_chunks(
            LONG_TEXT, mini_splitter
        )[0]


class TestChunkTextSections:
    def test_produces_standard_chunks_with_mini_chunks(self):
        document = _make_document([Section(type=SectionType.TEXT, text=LONG_TEXT)])
        chunks = chunk_text_sections(
            document.sections, document, chunk_token_limit=512, mini_chunk_size=150
        )

        assert chunks, "长文本应当至少产出一个 chunk"
        for chunk in chunks:
            assert chunk.chunk_level == "standard"
            assert chunk.section_type == SectionType.TEXT
            assert chunk.is_large_chunk is False
            assert chunk.content
            assert chunk.blurb
            assert chunk.title_prefix == "文档标题\n"
            # mini-chunk 偏移同样要能映射回自身 content
            if chunk.mini_chunk_texts:
                assert chunk.mini_chunk_offsets is not None
                assert len(chunk.mini_chunk_texts) == len(chunk.mini_chunk_offsets)
                for text, (start, end) in zip(
                    chunk.mini_chunk_texts, chunk.mini_chunk_offsets
                ):
                    assert chunk.content[start:end] == text

    def test_chunk_ids_start_at_given_offset(self):
        document = _make_document([Section(type=SectionType.TEXT, text=LONG_TEXT)])
        chunks = chunk_text_sections(
            document.sections, document, chunk_id_start=100
        )
        assert [c.chunk_id for c in chunks] == list(
            range(100, 100 + len(chunks))
        )

    def test_section_continuation_flag(self):
        document = _make_document([Section(type=SectionType.TEXT, text=LONG_TEXT)])
        # 用较小的 chunk_token_limit 保证长文本被切成多块
        chunks = chunk_text_sections(
            document.sections, document, chunk_token_limit=100
        )
        assert len(chunks) > 1, "本用例需要多块文本"
        assert chunks[0].section_continuation is False
        assert all(c.section_continuation is True for c in chunks[1:])

    def test_title_prefix_empty_without_title(self):
        document = _make_document(
            [Section(type=SectionType.TEXT, text="短文本")], title=None
        )
        chunks = chunk_text_sections(document.sections, document)
        assert chunks[0].title_prefix == ""

    def test_multiple_text_sections_are_concatenated(self):
        document = _make_document(
            [
                Section(type=SectionType.TEXT, text="第一段"),
                Section(type=SectionType.TEXT, text="第二段"),
            ]
        )
        chunks = chunk_text_sections(document.sections, document)
        assert len(chunks) == 1
        assert "第一段" in chunks[0].content
        assert "第二段" in chunks[0].content

    def test_non_text_sections_are_ignored(self):
        document = _make_document(
            [
                Section(type=SectionType.IMAGE, image_file_id="img-1"),
                Section(type=SectionType.TABULAR, text="| a | b |"),
            ]
        )
        assert chunk_text_sections(document.sections, document) == []

    def test_empty_sections_return_empty_list(self):
        assert chunk_text_sections([], _make_document([])) == []


class TestGenerateLargeChunks:
    """注意：本函数返回的大 chunk，其 `chunk_id` 继承自组内第一个成员（占位），
    真正的编号由 `pipeline.py` 在合并后统一重新分配（`lc.chunk_id = chunk_id`），
    分配结果使 `large_chunk_id` 与自身 `chunk_id` 自指一致。因此这里只断言
    `large_chunk_id` 的分配，`chunk_id` 的全局唯一性由 process_document 用例覆盖。
    """

    def test_groups_by_ratio(self):
        standards = [_make_text_chunk(i) for i in range(5)]
        large = generate_large_chunks(standards, ratio=2, chunk_id_start=100)

        # 5 个标准块按 ratio=2 分组 -> [0,1] [2,3] [4]，最后一组只剩 1 个不合并
        assert len(large) == 2
        assert [c.large_chunk_id for c in large] == [100, 101]

    def test_large_chunk_content_is_concatenation(self):
        standards = [_make_text_chunk(i, content=f"块{i}") for i in range(2)]
        large = generate_large_chunks(standards, ratio=2, chunk_id_start=10)

        assert len(large) == 1
        assert large[0].content == "块0\n\n块1"
        assert large[0].large_chunk_reference_ids == [0, 1]

    def test_large_chunk_flags(self):
        standards = [_make_text_chunk(i) for i in range(2)]
        large = generate_large_chunks(standards, ratio=2)[0]

        assert large.is_large_chunk is True
        assert large.chunk_level == "large"
        assert large.large_chunk_id == 0

    def test_large_chunks_carry_no_mini_chunks(self):
        """Embedder 约定：large chunk 携带 mini-chunk 会直接抛 RuntimeError。"""
        standards = [
            _make_text_chunk(i, mini=[f"mini-{i}-a", f"mini-{i}-b"]) for i in range(4)
        ]
        large = generate_large_chunks(standards, ratio=2, chunk_id_start=50)

        assert large
        for chunk in large:
            assert chunk.mini_chunk_texts is None
            assert chunk.large_chunk_reference_ids, "large chunk 需记录来源标准块"

    def test_source_chunks_get_large_chunk_id(self):
        standards = [_make_text_chunk(i) for i in range(4)]
        generate_large_chunks(standards, ratio=2, chunk_id_start=200)

        assert [c.large_chunk_id for c in standards] == [200, 200, 201, 201]

    def test_single_remaining_group_is_not_merged(self):
        standards = [_make_text_chunk(i) for i in range(3)]
        large = generate_large_chunks(standards, ratio=2, chunk_id_start=0)

        assert len(large) == 1
        assert standards[-1].large_chunk_id is None

    def test_existing_large_chunks_are_not_re_merged(self):
        standards = [_make_text_chunk(i) for i in range(2)]
        already_large = generate_large_chunks(standards, ratio=2, chunk_id_start=10)
        combined = standards + already_large

        second_pass = generate_large_chunks(combined, ratio=2, chunk_id_start=90)

        assert all(not c.large_chunk_reference_ids or c.chunk_level == "large" for c in second_pass)

    def test_below_ratio_returns_nothing(self):
        assert generate_large_chunks([_make_text_chunk(0)], ratio=2) == []
        assert generate_large_chunks([], ratio=2) == []


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    """端到端处理一份长 Markdown，返回 (Document, chunks, images)。

    关闭嵌入 / 富化 / 图片处理 / 向量库，全程不依赖外部服务。
    """
    from pipeline import process_document

    work_dir = tmp_path_factory.mktemp("chunk_pipeline")
    source = work_dir / "long.md"
    source.write_text(
        "\n".join(
            f"## 小节 {i}\n\n这是第 {i} 个小节的正文，需要足够长度以触发多块切分与大块合并。\n"
            for i in range(150)
        ),
        encoding="utf-8",
    )

    document, chunks, images = process_document(
        str(source),
        str(work_dir / "out"),
        chunk_token_limit=100,
        mini_chunk_size=50,
        enable_large_chunks=True,
        large_chunk_ratio=4,
        enable_contextual_rag=False,
        enable_embedding=False,
        enable_vector_store=False,
        enable_enrichment=False,
        enable_image_processing=False,
    )
    return document, chunks, images


def _children(chunks: list[DocAwareChunk]) -> list[DocAwareChunk]:
    """筛出「被合并进大块」的子块。

    注意不能只判 `large_chunk_id is not None`：大块的该字段是**自指**的，
    只按非空筛选会把大块自己也当成子块（`vector_store/searcher.py` 正是靠先判
    `is_large_chunk` 才避开这个坑）。
    """
    return [
        c
        for c in chunks
        if c.large_chunk_id is not None and c.chunk_level != "large"
    ]


class TestProcessDocumentIntegration:
    """端到端跑 process_document。

    这是唯一覆盖「pipeline 合并后重新分配 large chunk 编号」这条逻辑的用例，
    而 chunk_id 全局唯一正是 Qdrant point id（uuid5(f"{document_id}_{chunk_id}")）
    互不覆盖的前提。
    """

    def test_returns_document_and_chunks(self, processed):
        document, chunks, images = processed
        assert document.id
        assert chunks
        assert isinstance(images, list)

    def test_all_chunks_belong_to_same_document(self, processed):
        document, chunks, _ = processed
        assert all(c.source_document.id == document.id for c in chunks)

    def test_chunk_ids_are_globally_unique(self, processed):
        """编号重复会让两个块落到同一个 Qdrant point 上互相覆盖。"""
        _, chunks, _ = processed
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "chunk_id 存在重复"

    def test_large_chunks_self_reference_and_carry_no_mini(self, processed):
        _, chunks, _ = processed
        large = [c for c in chunks if c.chunk_level == "large"]

        assert large, "长文档应当生成大块"
        for lc in large:
            assert lc.is_large_chunk is True
            assert lc.large_chunk_id == lc.chunk_id, "大块的 large_chunk_id 应自指"
            assert lc.mini_chunk_texts is None
            assert len(lc.large_chunk_reference_ids) > 1

    def test_children_point_to_existing_large_chunk(self, processed):
        _, chunks, _ = processed
        by_id = {c.chunk_id: c for c in chunks}

        children = _children(chunks)
        assert children, "应当有块被合并进大块"

        for chunk in children:
            parent = by_id.get(chunk.large_chunk_id)
            assert parent is not None, f"块 {chunk.chunk_id} 指向了不存在的大块"
            assert parent.chunk_level == "large"
            assert chunk.chunk_id in parent.large_chunk_reference_ids

    def test_self_referencing_large_chunks_are_not_children(self, processed):
        """大块自指的 large_chunk_id 不应被当作父子关系。"""
        _, chunks, _ = processed
        children = _children(chunks)

        assert all(c.chunk_level != "large" for c in children)
        assert any(c.large_chunk_id is not None for c in chunks if c.chunk_level == "large")

    def test_large_chunk_content_covers_all_children(self, processed):
        _, chunks, _ = processed
        by_id = {c.chunk_id: c for c in chunks}

        for lc in (c for c in chunks if c.chunk_level == "large"):
            for child_id in lc.large_chunk_reference_ids:
                assert by_id[child_id].content in lc.content

    def test_表格行从正文去重不再进入文本块(self, sample_file, tmp_path):
        """修复前：删除逻辑用「原始行 == CSV 行」全等匹配，单元格一行一个的
        PDF 一行都删不掉，表格内容同时出现在文本块与表格块里。"""
        from pipeline import process_document

        _, chunks, _ = process_document(
            sample_file("sample.pdf"),
            str(tmp_path / "out"),
            enable_large_chunks=False,
            enable_contextual_rag=False,
            enable_embedding=False,
            enable_vector_store=False,
            enable_image_processing=False,
        )

        text_content = "\n".join(
            c.content
            for c in chunks
            if c.section_type == SectionType.TEXT and not c.is_large_chunk
        )
        tabular_content = "\n".join(
            c.content for c in chunks if c.section_type == SectionType.TABULAR
        )

        assert "Google Drive" in tabular_content, "表格块应保留单元格内容"
        assert "Google Drive" not in text_content, "单元格不应再重复出现在文本块里"
        assert "OAuth 2.0 Service Account" not in text_content
