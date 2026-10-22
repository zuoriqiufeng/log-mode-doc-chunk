"""日志模式库测试：LogPattern 模型、解析器别名归一化、分块与 payload。"""

from __future__ import annotations

import json
import re

import pytest

from log_patterns.chunker import LogPatternChunker
from log_patterns.models import SEVERITY_LEVELS, LogPattern
from log_patterns.parsers import (
    CsvLogPatternParser,
    JsonLogPatternParser,
    YamlLogPatternParser,
    get_parser,
)
from log_patterns.payload import build_pattern_payload


def _pattern(**kwargs) -> LogPattern:
    params = {
        "pattern_id": "ORA-00257",
        "log_fingerprint": ["ORA-00257", "archiver error"],
        "component": "iatrack",
        "severity": "high",
        "symptom": "归档日志写满，数据库挂起",
        "root_cause": "归档目录空间不足",
        "remediation": ["清理归档目录", "扩大 FRA 空间"],
        "error_codes": ["ORA-00257"],
        "db_types": ["oracle"],
        "target_types": ["doris"],
        "dimension": "resource",
        "grade": "confirmed",
        "counter_evidence": "若归档目录有剩余空间，则不是本模式",
        "false_positive": "误报：临时备份占用",
        "log_samples": ["2026-01-01 ERROR archiver error: ORA-00257"],
        "source_note": "现场案例",
        "updated_at": "2026-01-01",
    }
    params.update(kwargs)
    return LogPattern(**params)


class TestLogPatternFields:
    def test_fingerprint_text_joins_three_parts(self):
        pattern = _pattern()
        assert pattern.fingerprint_text == "ORA-00257 archiver error iatrack ORA-00257"

    def test_fingerprint_text_skips_empty_parts(self):
        pattern = _pattern(log_fingerprint=["A"], error_codes=[])
        assert pattern.fingerprint_text == "A iatrack"

    def test_full_text_includes_all_filled_sections(self):
        text = _pattern().full_text()
        for expected in (
            "Pattern ID: ORA-00257",
            "Component: iatrack",
            "Severity: high",
            "Error codes: ORA-00257",
            "DB types: oracle",
            "Target types: doris",
            "Dimension: resource",
            "Grade: confirmed",
            "Log fingerprint: ORA-00257, archiver error",
            "Symptom: 归档日志写满，数据库挂起",
            "False positive: 误报：临时备份占用",
            "Counter evidence: 若归档目录有剩余空间，则不是本模式",
            "Root cause: 归档目录空间不足",
            "Remediation:",
            "  - 清理归档目录",
            "Log samples:",
            "  | 2026-01-01 ERROR archiver error: ORA-00257",
            "Source note: 现场案例",
            "Updated at: 2026-01-01",
        ):
            assert expected in text

    def test_full_text_omits_empty_sections(self):
        text = _pattern(
            symptom="", false_positive="", counter_evidence="",
            root_cause="", remediation=[], log_samples=[],
        ).full_text()
        assert "Symptom:" not in text
        assert "Root cause:" not in text
        assert "Remediation:" not in text
        assert "False positive:" not in text
        assert "Counter evidence:" not in text
        assert "Log samples:" not in text

    def test_updated_at_defaults_to_today(self):
        pattern = LogPattern(
            pattern_id="p", log_fingerprint=["f1", "f2"], component="iatrack",
            severity="high", dimension="unknown", grade="clue", updated_at="",
        )
        assert pattern.updated_at == ""

        fresh = LogPattern(
            pattern_id="p", log_fingerprint=["f1", "f2"], component="iatrack",
            severity="high", dimension="unknown", grade="clue",
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fresh.updated_at)


class TestLogPatternMiniTexts:
    def test_full_pattern_yields_four_minis_in_order(self):
        minis = _pattern().mini_texts()
        assert len(minis) == 4
        # mini-1 = 指纹 + 真实日志原文（按日志文本匹配导向）
        assert minis[0] == (
            "ORA-00257 archiver error iatrack ORA-00257 "
            "2026-01-01 ERROR archiver error: ORA-00257"
        )
        assert minis[1] == "归档目录空间不足"
        assert minis[2] == "清理归档目录 扩大 FRA 空间"
        # mini-4 = 症状 + 误判提示 + 反证
        assert minis[3] == "归档日志写满，数据库挂起 误报：临时备份占用 若归档目录有剩余空间，则不是本模式"

    def test_minimal_pattern_still_yields_two_minis(self):
        minis = _pattern(
            root_cause="", remediation=[], symptom="",
            false_positive="", counter_evidence="", log_samples=[],
        ).mini_texts()
        assert len(minis) == 2
        assert minis[0] == minis[1]

    def test_pattern_without_fingerprint_falls_back_to_pattern_id(self):
        minis = _pattern(
            log_fingerprint=[],
            component="",
            error_codes=[],
            root_cause="",
            remediation=[],
            symptom="",
            false_positive="",
            counter_evidence="",
            log_samples=[],
        ).mini_texts()
        assert minis == ["ORA-00257", "ORA-00257"]

    def test_mini_count_never_exceeds_four(self):
        assert 2 <= len(_pattern().mini_texts()) <= 4


class TestLogPatternValidate:
    def test_valid_pattern_has_no_errors(self):
        assert _pattern().validate() == []

    @pytest.mark.parametrize(
        ("kwargs", "expected_fragment"),
        [
            ({"pattern_id": ""}, "pattern_id"),
            ({"pattern_id": "   "}, "pattern_id"),
            ({"component": ""}, "component"),
            ({"component": "foobar"}, "component"),
            ({"log_fingerprint": []}, "log_fingerprint"),
            ({"log_fingerprint": ["only-one"]}, "log_fingerprint"),
            ({"severity": ""}, "severity"),
            ({"severity": "urgent"}, "severity"),
            ({"dimension": ""}, "dimension"),
            ({"dimension": "latency"}, "dimension"),
            ({"grade": ""}, "grade"),
            ({"grade": "certain"}, "grade"),
            ({"db_types": ["mongodb"]}, "db_types"),
            ({"target_types": ["kafka"]}, "target_types"),
            ({"db_types": ["doris"], "target_types": ["doris"]}, "交叉"),
            ({"updated_at": "2026-01-01T00:00:00"}, "updated_at"),
            ({"updated_at": ""}, "updated_at"),
        ],
    )
    def test_invalid_fields_reported(self, kwargs, expected_fragment):
        errors = _pattern(**kwargs).validate()
        assert any(expected_fragment in e for e in errors)

    def test_severity_is_case_insensitive(self):
        assert _pattern(severity="CRITICAL").validate() == []

    def test_dimension_and_grade_are_case_insensitive(self):
        assert _pattern(dimension="RESOURCE", grade="CONFIRMED").validate() == []

    def test_empty_severity_is_rejected(self):
        assert any("severity" in e for e in _pattern(severity="").validate())

    def test_severity_levels_are_the_documented_four(self):
        assert SEVERITY_LEVELS == {"critical", "high", "medium", "low"}

    def test_component_enum_covers_v21(self):
        from log_patterns.models import COMPONENTS

        assert {"iatrack", "iadumper", "ialoader", "iahelper", "iamonitor", "iadiff", "iaproxy"} <= COMPONENTS

    def test_dimension_enum_matches_error_semantics(self):
        from log_patterns.models import DIMENSIONS

        assert DIMENSIONS == {
            "log_readable", "state_machine", "permission", "connectivity",
            "resource", "consistency", "time_sync", "unknown",
        }


class TestParsers:
    def test_json_array(self, tmp_path):
        path = tmp_path / "patterns.json"
        path.write_text(
            json.dumps([{"pattern_id": "P1", "log_fingerprint": "a;b", "component": "db"}]),
            encoding="utf-8",
        )
        patterns = JsonLogPatternParser().parse(str(path))
        assert len(patterns) == 1
        assert patterns[0].pattern_id == "P1"
        assert patterns[0].log_fingerprint == ["a", "b"]

    def test_json_wrapped_in_patterns_key(self, tmp_path):
        path = tmp_path / "wrapped.json"
        path.write_text(
            json.dumps({"patterns": [{"pattern_id": "P1", "component": "db", "log_fingerprint": ["x"]}]}),
            encoding="utf-8",
        )
        assert len(JsonLogPatternParser().parse(str(path))) == 1

    def test_json_single_object(self, tmp_path):
        path = tmp_path / "single.json"
        path.write_text(
            json.dumps({"pattern_id": "P1", "component": "db", "log_fingerprint": ["x"]}),
            encoding="utf-8",
        )
        assert len(JsonLogPatternParser().parse(str(path))) == 1

    def test_yaml_patterns(self, tmp_path):
        path = tmp_path / "patterns.yaml"
        path.write_text(
            "patterns:\n"
            "  - patternId: Y1\n"
            "    module: db\n"
            "    fingerprint:\n"
            "      - hello\n",
            encoding="utf-8",
        )
        patterns = YamlLogPatternParser().parse(str(path))
        assert patterns[0].pattern_id == "Y1"
        assert patterns[0].component == "db"
        assert patterns[0].log_fingerprint == ["hello"]

    def test_csv_with_aliases_and_multi_value_delimiters(self, tmp_path):
        path = tmp_path / "patterns.csv"
        path.write_text(
            "patternId,module,level,errorCodes,fix,solution\n"
            "C1,oracle,HIGH,ORA-1;ORA-2,清归档|扩容,\n",
            encoding="utf-8",
        )
        patterns = CsvLogPatternParser().parse(str(path))

        assert len(patterns) == 1
        pattern = patterns[0]
        assert pattern.pattern_id == "C1"
        assert pattern.component == "oracle"
        assert pattern.severity == "HIGH"
        assert pattern.error_codes == ["ORA-1", "ORA-2"]
        # fix 与 solution 都映射到 remediation；空单元格不覆盖已填内容
        assert pattern.remediation == ["清归档", "扩容"]

    def test_empty_alias_column_does_not_clobber_filled_one(self, tmp_path):
        """回归：solution 列为空时，不应把 fix 列的内容清掉。"""
        path = tmp_path / "clobber.csv"
        path.write_text(
            "patternId,component,fix,solution\nC1,db,重启实例,\n",
            encoding="utf-8",
        )
        assert CsvLogPatternParser().parse(str(path))[0].remediation == ["重启实例"]

    def test_later_non_empty_alias_wins(self, tmp_path):
        path = tmp_path / "wins.csv"
        path.write_text(
            "patternId,component,fix,solution\nC1,db,重启实例,扩容磁盘\n",
            encoding="utf-8",
        )
        assert CsvLogPatternParser().parse(str(path))[0].remediation == ["扩容磁盘"]

    def test_csv_skips_blank_rows(self, tmp_path):
        path = tmp_path / "blank.csv"
        path.write_text("patternId,component\nC1,db\n,\n", encoding="utf-8")
        assert len(CsvLogPatternParser().parse(str(path))) == 1

    def test_json_parses_all_v21_fields(self, tmp_path):
        path = tmp_path / "v21.json"
        path.write_text(
            json.dumps(
                {
                    "pattern_id": "LP-0087",
                    "log_fingerprint": ["REORGANIZE PARTITION", "parse ddl error"],
                    "component": "iatrack",
                    "severity": "high",
                    "symptom": "分区结构未变更",
                    "root_cause": "解析器不支持该语法",
                    "remediation": ["grep 确认", "手工补 DDL"],
                    "error_codes": [],
                    "db_types": ["mysql"],
                    "target_types": ["doris"],
                    "dimension": "consistency",
                    "grade": "confirmed",
                    "counter_evidence": "目标端已变更则不是本模式",
                    "false_positive": "无害预解析失败",
                    "log_samples": ["2026-10-13 WARN parse sql failed, sql:ALTER ..."],
                    "source_note": "实战",
                    "updated_at": "2026-10-13",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        pattern = JsonLogPatternParser().parse(str(path))[0]
        assert pattern.target_types == ["doris"]
        assert pattern.dimension == "consistency"
        assert pattern.grade == "confirmed"
        assert pattern.counter_evidence == "目标端已变更则不是本模式"
        assert pattern.log_samples == ["2026-10-13 WARN parse sql failed, sql:ALTER ..."]
        assert pattern.validate() == []

    def test_new_field_aliases_in_csv(self, tmp_path):
        path = tmp_path / "alias.csv"
        path.write_text(
            "patternId,component,confidence,dim,targetTypes,counter,samples\n"
            "C1,iatrack,clue,resource,doris,非本模式,s1;s2\n",
            encoding="utf-8",
        )
        pattern = CsvLogPatternParser().parse(str(path))[0]
        assert pattern.grade == "clue"
        assert pattern.dimension == "resource"
        assert pattern.target_types == ["doris"]
        assert pattern.counter_evidence == "非本模式"
        assert pattern.log_samples == ["s1", "s2"]

    def test_component_historical_alias_normalized(self, tmp_path):
        path = tmp_path / "alias_comp.json"
        path.write_text(
            json.dumps(
                {
                    "pattern_id": "P1",
                    "component": "loader",
                    "log_fingerprint": ["a", "b"],
                }
            ),
            encoding="utf-8",
        )
        assert JsonLogPatternParser().parse(str(path))[0].component == "ialoader"

    def test_unknown_keys_kept_in_metadata(self, tmp_path):
        path = tmp_path / "unknown.json"
        path.write_text(
            json.dumps(
                {
                    "pattern_id": "P1",
                    "component": "iatrack",
                    "log_fingerprint": ["a", "b"],
                    "future_field": "留档",
                }
            ),
            encoding="utf-8",
        )
        pattern = JsonLogPatternParser().parse(str(path))[0]
        assert pattern.metadata["unrecognized"] == {"future_field": "留档"}
        # 未知键不影响正常字段
        assert pattern.pattern_id == "P1"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("a.json", JsonLogPatternParser),
            ("a.yaml", YamlLogPatternParser),
            ("a.yml", YamlLogPatternParser),
            ("a.csv", CsvLogPatternParser),
            ("a.tsv", CsvLogPatternParser),
        ],
    )
    def test_get_parser_dispatch(self, name, expected):
        assert isinstance(get_parser(name), expected)

    def test_get_parser_rejects_unsupported_extension(self):
        with pytest.raises(ValueError, match="不支持的日志模式文件格式"):
            get_parser("patterns.txt")


class TestBuildPatternPayload:
    def test_standard_payload_fields(self):
        payload = build_pattern_payload(_pattern(), chunk_type="standard")

        assert payload["is_log_pattern"] is True
        assert payload["pattern_id"] == "ORA-00257"
        assert payload["chunk_type"] == "standard"
        # log_fingerprint 在 payload 中保持 list 类型（不可拍平成字符串）
        assert payload["log_fingerprint"] == ["ORA-00257", "archiver error"]
        assert payload["keywords"] == payload["log_fingerprint"]
        assert payload["severity"] == "high"
        assert payload["error_codes"] == ["ORA-00257"]

    def test_payload_carries_retrieval_meta_keys(self):
        """透传口径对齐 PATTERN_META_KEYS：含 target_types 与 dimension。"""
        payload = build_pattern_payload(_pattern(), chunk_type="standard")
        assert payload["target_types"] == ["doris"]
        assert payload["dimension"] == "resource"

    def test_grade_and_samples_stay_off_payload(self):
        """grade/log_samples/counter_evidence 仅落库留档，不进检索 payload。"""
        payload = build_pattern_payload(_pattern(), chunk_type="standard")
        assert "grade" not in payload
        assert "log_samples" not in payload
        assert "counter_evidence" not in payload

    def test_chunk_type_is_recorded(self):
        assert build_pattern_payload(_pattern(), chunk_type="mini")["chunk_type"] == "mini"


class TestLogPatternChunker:
    def test_one_standard_chunk_per_pattern(self):
        chunks = LogPatternChunker().chunk([_pattern(), _pattern(pattern_id="P2")])

        assert len(chunks) == 2
        assert [c.chunk_id for c in chunks] == [0, 1]
        for chunk in chunks:
            assert chunk.chunk_level == "log_pattern_standard"
            assert chunk.section_type.value == "text"
            assert chunk.content
            assert chunk.blurb == chunk.blurb[:150]

    def test_chunk_id_start_offset(self):
        chunks = LogPatternChunker().chunk([_pattern()], chunk_id_start=42)
        assert chunks[0].chunk_id == 42

    def test_document_id_uses_prefix_and_pattern_id(self):
        chunk = LogPatternChunker().chunk([_pattern()])[0]
        assert chunk.source_document.id == "log_pattern_ORA-00257"
        assert chunk.source_document.semantic_identifier == "ORA-00257"
        assert chunk.source_document.source == "LOG_PATTERN"

    def test_mini_chunks_have_matching_payloads(self):
        chunk = LogPatternChunker().chunk([_pattern()])[0]

        assert chunk.mini_chunk_texts is not None
        assert 2 <= len(chunk.mini_chunk_texts) <= 4
        assert chunk.mini_chunk_payloads is not None
        assert len(chunk.mini_chunk_payloads) == len(chunk.mini_chunk_texts)

        for mini_text, payload in zip(chunk.mini_chunk_texts, chunk.mini_chunk_payloads):
            assert payload["chunk_type"] == "mini"
            assert payload["is_log_pattern"] is True
            assert payload["mini_content_preview"] == mini_text[:100]

    def test_standard_chunk_carries_pattern_payload(self):
        chunk = LogPatternChunker().chunk([_pattern()])[0]

        assert chunk.custom_payload["is_log_pattern"] is True
        assert chunk.custom_payload["pattern_id"] == "ORA-00257"
        assert chunk.custom_payload["chunk_type"] == "standard"

    def test_custom_prefix(self):
        chunk = LogPatternChunker(document_id_prefix="lp").chunk([_pattern()])[0]
        assert chunk.source_document.id == "lp_ORA-00257"

    def test_empty_input(self):
        assert LogPatternChunker().chunk([]) == []
