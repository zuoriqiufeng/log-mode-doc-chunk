"""数据模型测试：SectionType / Section / Document / DocAwareChunk / IndexChunk。"""

from __future__ import annotations

from models import DocAwareChunk, Document, IndexChunk, Section, SectionType


def _make_document(**kwargs) -> Document:
    params = {"id": "doc-1", "semantic_identifier": "doc-1", "sections": []}
    params.update(kwargs)
    return Document(**params)


def _make_chunk(**kwargs) -> DocAwareChunk:
    params = {
        "source_document": _make_document(),
        "chunk_id": 0,
        "content": "content",
        "blurb": "blurb",
    }
    params.update(kwargs)
    return DocAwareChunk(**params)


class TestSectionType:
    def test_values(self):
        assert SectionType.TEXT.value == "text"
        assert SectionType.IMAGE.value == "image"
        assert SectionType.TABULAR.value == "tabular"

    def test_is_str_enum(self):
        # 继承 str 是为了让枚举可直接参与比较与序列化
        assert SectionType.TEXT == "text"
        assert isinstance(SectionType.TEXT, str)


class TestDocument:
    def test_get_text_content_joins_with_blank_line(self):
        doc = _make_document(
            sections=[
                Section(type=SectionType.TEXT, text="first"),
                Section(type=SectionType.TEXT, text="second"),
            ]
        )
        assert doc.get_text_content() == "first\n\nsecond"

    def test_get_text_content_treats_none_as_empty(self):
        doc = _make_document(
            sections=[
                Section(type=SectionType.TEXT, text="only"),
                Section(type=SectionType.IMAGE, image_file_id="img-1"),
            ]
        )
        assert doc.get_text_content() == "only\n\n"

    def test_get_title_for_document_index(self):
        assert _make_document(title="标题").get_title_for_document_index() == "标题"
        assert _make_document().get_title_for_document_index() is None

    def test_defaults(self):
        doc = _make_document()
        assert doc.source == "FILE"
        assert doc.metadata == {}
        assert doc.doc_updated_at is None


class TestDocAwareChunkDefaults:
    def test_standard_chunk_defaults(self):
        chunk = _make_chunk()
        assert chunk.chunk_level == "standard"
        assert chunk.is_large_chunk is False
        assert chunk.section_continuation is False
        assert chunk.mini_chunk_texts is None
        assert chunk.mini_chunk_offsets is None
        assert chunk.large_chunk_id is None
        assert chunk.doc_summary == ""
        assert chunk.chunk_context == ""

    def test_large_chunk_ids_default_to_empty_list(self):
        assert _make_chunk().large_chunk_reference_ids == []

    def test_structured_payload_defaults(self):
        chunk = _make_chunk()
        assert chunk.custom_payload == {}
        assert chunk.mini_chunk_payloads is None

    def test_mutable_defaults_are_not_shared_between_instances(self):
        """两个实例不得共享同一份 list/dict，否则一处写入会污染另一处。"""
        first, second = _make_chunk(), _make_chunk()
        first.custom_payload["k"] = "v"
        first.large_chunk_reference_ids.append(1)
        assert second.custom_payload == {}
        assert second.large_chunk_reference_ids == []


class TestIndexChunk:
    def test_inherits_doc_aware_chunk(self):
        chunk = IndexChunk(
            source_document=_make_document(),
            chunk_id=0,
            content="c",
            blurb="b",
        )
        assert isinstance(chunk, DocAwareChunk)

    def test_default_embeddings_are_empty(self):
        chunk = IndexChunk(
            source_document=_make_document(),
            chunk_id=0,
            content="c",
            blurb="b",
        )
        assert chunk.embeddings.full_embedding == []
        assert chunk.embeddings.mini_chunk_embeddings == []
        assert chunk.title_embedding is None
