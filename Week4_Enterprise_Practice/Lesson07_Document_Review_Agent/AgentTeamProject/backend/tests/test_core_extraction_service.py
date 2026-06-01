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
