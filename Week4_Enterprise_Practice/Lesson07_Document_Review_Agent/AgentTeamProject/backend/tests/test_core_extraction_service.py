import json

from app.services import rag_service, review_config_service, water_review_service
from app.services.core_extraction_service import build_core_extraction_chunks
from app.services.water_review_models import ReviewChunk


def _chunk(chunk_id: str, text: str, section: str) -> ReviewChunk:
    index = int(chunk_id.rsplit("-", 1)[-1])
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[index, index],
        bbox_list=[],
        table_refs=[],
        metadata={},
        char_start=index * 100,
        char_end=index * 100 + len(text),
    )


def test_build_core_extraction_chunks_falls_back_to_project_and_earthwork_keywords(tmp_path):
    chunks = [
        _chunk("chunk-0001", "项目名称：测试项目。建设单位：测试公司。建设地点位于北京市。", "项目概况"),
        _chunk("chunk-0002", "水土保持监测采用定点监测和巡查。", "监测"),
        _chunk("chunk-0003", "土石方平衡：挖方10.00万m3，填方8.00万m3，借方0.00万m3，弃方2.00万m3。", "土石方平衡"),
    ]

    result = build_core_extraction_chunks(chunks, "session-core", tmp_path, store_factory=lambda: None)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0001", "chunk-0003"]
    assert result.mode in {"bm25", "keyword"}
    assert result.trace["selected_count"] == 2
    assert result.trace["fallback_used"] is True
    assert (tmp_path / "core_extraction_chunks.json").exists()


def test_build_core_extraction_chunks_returns_all_chunks_when_no_core_match(tmp_path):
    chunks = [
        _chunk("chunk-0001", "附图目录。", "附图"),
        _chunk("chunk-0002", "附件清单。", "附件"),
    ]

    result = build_core_extraction_chunks(chunks, "session-empty", tmp_path, store_factory=lambda: None)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0001", "chunk-0002"]
    assert result.mode == "all_chunks_fallback"
    assert result.trace["selected_count"] == 2


def test_core_extraction_trace_records_mode_and_selected_chunks(tmp_path):
    chunks = [
        _chunk("chunk-0001", "项目名称：测试项目。建设单位：测试公司。建设地点位于北京市。", "项目概况"),
        _chunk("chunk-0002", "水土保持监测采用定点监测和巡查。", "监测"),
        _chunk("chunk-0003", "土石方平衡：挖方10.00万m3，填方8.00万m3，借方0.00万m3，弃方2.00万m3。", "土石方平衡"),
    ]

    result = build_core_extraction_chunks(chunks, "session-trace", tmp_path, store_factory=lambda: None)
    trace = json.loads((tmp_path / "core_extraction_chunks.json").read_text(encoding="utf-8"))

    assert trace["mode"] == result.mode
    assert trace["input_count"] == 3
    assert trace["selected_count"] == 2
    assert [chunk["chunk_id"] for chunk in trace["chunks"]] == ["chunk-0001", "chunk-0003"]
    assert [chunk["section"] for chunk in trace["chunks"]] == ["项目概况", "土石方平衡"]


def test_run_pipeline_skips_core_selection_when_prerag_cache_hits(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "extracted_fields.json").write_text(json.dumps([{"field_name": "project_name", "value": "缓存项目"}]), encoding="utf-8")
    (artifact_dir / "langextract_facts.json").write_text("[]", encoding="utf-8")
    (artifact_dir / "langextract_fact_index.json").write_text(json.dumps({"fact_count": 0, "fields": [], "by_field": {}}), encoding="utf-8")
    (artifact_dir / "cross_chapter_findings.json").write_text("[]", encoding="utf-8")

    chunks = [_chunk("chunk-0001", "项目名称：缓存项目。", "项目概况")]
    monkeypatch.setattr(water_review_service, "parse_document", lambda _file_path: [])
    monkeypatch.setattr(water_review_service, "build_chunks", lambda _blocks: chunks)

    def fail_core_selection(*_args, **_kwargs):
        raise AssertionError("core selection should not run when prerag cache hits")

    monkeypatch.setattr(water_review_service, "build_core_extraction_chunks", fail_core_selection)
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda *_args, **_kwargs: {"issues": [], "retrievals": [], "cache_hits": {}, "index_manifest": {}},
    )
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])
    monkeypatch.setattr(water_review_service, "_issues_from_configured_rules", lambda *_args, **_kwargs: [])

    result = water_review_service.run_pipeline("missing-source.pdf", str(artifact_dir), "session-cache")

    assert result["cache_hits"]["prerag_artifacts"] is True
    assert result["fields"] == [{"field_name": "project_name", "value": "缓存项目"}]
