import json
from types import SimpleNamespace

from app.services import rag_service, review_config_service, water_review_service
from app.services import core_extraction_service
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


def test_build_core_extraction_chunks_does_not_build_vector_store_by_default(tmp_path, monkeypatch):
    chunks = [
        _chunk("chunk-0001", "项目名称：测试项目。建设单位：测试公司。", "项目概况"),
        _chunk("chunk-0002", "土石方平衡：挖方10.00万m3，填方10.00万m3。", "土石方平衡"),
    ]

    def fail_default_store(*_args, **_kwargs):
        raise AssertionError("default core extraction should not rebuild vector store")

    monkeypatch.setattr(core_extraction_service, "_default_store", fail_default_store)

    result = build_core_extraction_chunks(chunks, "session-no-vector", tmp_path)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0001", "chunk-0002"]
    assert result.mode in {"bm25", "keyword"}
    assert result.trace["fallback_used"] is True


def test_build_core_extraction_chunks_uses_injected_store_without_rebuild(tmp_path):
    chunks = [
        _chunk("chunk-0001", "无关章节。", "附件"),
        _chunk("chunk-0002", "项目名称：向量命中项目。", "项目概况"),
    ]

    class FakeStore:
        def __init__(self) -> None:
            self.query_count = 0

        def query(self, _query: str, top_k: int) -> list[dict]:
            self.query_count += 1
            return [
                {
                    "chunk_id": "chunk-0002",
                    "document": "项目名称：向量命中项目。",
                    "metadata": {"chunk_id": "chunk-0002", "chunk_index": 1},
                    "score": 0.1,
                    "retrieval_sources": ["vector"],
                    "source_ranks": {"vector": 1},
                }
            ]

    fake_store = FakeStore()

    result = build_core_extraction_chunks(chunks, "session-injected-vector", tmp_path, store_factory=lambda: fake_store)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0002"]
    assert result.mode == "vector"
    assert result.trace["fallback_used"] is False
    assert fake_store.query_count == 2


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
    (artifact_dir / "prerag_cache_manifest.json").write_text(
        json.dumps(water_review_service._prerag_cache_manifest(), ensure_ascii=False),
        encoding="utf-8",
    )

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


def test_run_pipeline_rejects_legacy_prerag_cache_without_policy_manifest(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "extracted_fields.json").write_text(
        json.dumps([{"field_name": "topsoil_stripping", "value": "旧缓存表土剥离"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "langextract_facts.json").write_text(
        json.dumps([{"fact_id": "old-topsoil", "field_name": "topsoil_stripping", "value": "旧缓存表土剥离"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "langextract_fact_index.json").write_text(
        json.dumps({"fact_count": 1, "fields": ["topsoil_stripping"], "by_field": {"topsoil_stripping": ["old-topsoil"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "cross_chapter_findings.json").write_text("[]", encoding="utf-8")

    chunks = [_chunk("chunk-0001", "项目名称：新策略项目。", "项目概况")]
    monkeypatch.setattr(water_review_service, "parse_document", lambda _file_path: [])
    monkeypatch.setattr(water_review_service, "build_chunks", lambda _blocks: chunks)
    monkeypatch.setattr(
        water_review_service,
        "build_core_extraction_chunks",
        lambda *_args, **_kwargs: SimpleNamespace(chunks=chunks, mode="keyword", trace={"selected_count": 1, "input_count": 1}),
    )
    monkeypatch.setattr(
        water_review_service,
        "extract_fields",
        lambda _chunks: [{"field_name": "project_name", "value": "新策略项目"}],
    )
    monkeypatch.setattr(water_review_service, "extract_table_facts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda *_args, **_kwargs: {"issues": [], "retrievals": [], "cache_hits": {}, "index_manifest": {}},
    )
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])
    monkeypatch.setattr(water_review_service, "_issues_from_configured_rules", lambda *_args, **_kwargs: [])

    result = water_review_service.run_pipeline("missing-source.pdf", str(artifact_dir), "session-legacy-cache")

    assert result["cache_hits"]["prerag_artifacts"] is False
    assert result["fields"] == [{"field_name": "project_name", "value": "新策略项目"}]
    facts = json.loads((artifact_dir / "langextract_facts.json").read_text(encoding="utf-8"))
    assert facts == []
    manifest = json.loads((artifact_dir / "prerag_cache_manifest.json").read_text(encoding="utf-8"))
    assert manifest == water_review_service._prerag_cache_manifest()
