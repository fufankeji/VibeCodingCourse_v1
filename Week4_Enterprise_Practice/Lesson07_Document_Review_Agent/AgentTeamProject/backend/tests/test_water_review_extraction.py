from app.services.water_review_extraction import extract_fields
from app.services.water_review_models import ReviewChunk, WATER_FIELDS


def _chunk(chunk_id: str, text: str, section: str = "项目概况", char_start: int = 0) -> ReviewChunk:
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[1, 1],
        bbox_list=[],
        table_refs=[],
        metadata={},
        char_start=char_start,
        char_end=char_start + len(text),
    )


def _by_name(fields: list[dict]) -> dict[str, dict]:
    return {field["field_name"]: field for field in fields}


def test_extract_fields_keeps_output_shape_but_only_populates_core_fields():
    text = (
        "项目名称：清河综合治理工程。\n"
        "建设单位：清河建设有限公司。\n"
        "建设地点：北京市海淀区。\n"
        "建设性质：新建。\n"
        "占地面积12.50hm2，扰动地表面积11.20hm2，防治责任范围面积12.80hm2。\n"
        "弃方去向为外运至合规消纳场，借方来自取土场，余方综合利用。\n"
        "水土保持监测采用定点监测和巡查。\n"
        "投资估算为320.00万元。\n"
        "防治措施包括工程措施、植物措施和临时措施。\n"
        "表土剥离、表土保存、表土回覆均已安排。\n"
    )

    fields = extract_fields([_chunk("chunk-0001", text)])
    by_name = _by_name(fields)

    assert [field["field_name"] for field in fields] == WATER_FIELDS
    assert by_name["project_name"]["value"] == "清河综合治理工程"
    assert by_name["construction_unit"]["value"] == "清河建设有限公司"
    assert by_name["construction_unit"]["extraction_status"] == "found"
    assert by_name["land_area"]["normalized_value"] == "12.50"
    assert by_name["comprehensive_utilization"]["value"] == "综合利用"
    assert by_name["spoil_destination"]["value"] == "外运"
    assert by_name["borrow_area"]["value"] == "取土场"

    non_core_fields = [
        "monitoring",
        "investment_estimate",
        "prevention_measures",
        "topsoil_stripping",
        "topsoil_preservation",
        "topsoil_backfill",
    ]
    for name in non_core_fields:
        assert by_name[name]["value"] == ""
        assert by_name[name]["normalized_value"] == ""
        assert by_name[name]["source_span"] is None
        assert by_name[name]["confidence"] == 35
        assert by_name[name]["extraction_status"] == "not_targeted"

    assert by_name["borrow_volume"]["value"] == ""
    assert by_name["borrow_volume"]["extraction_status"] == "not_found"


def test_extract_fields_populates_core_earthwork_fields():
    text = "土石方平衡：挖方10.50万m3，填方8.25万m3，借方1.00万m3，弃方3.25万m3。"

    fields = _by_name(extract_fields([_chunk("chunk-0001", text, "土石方平衡")]))

    assert fields["excavation_volume"]["value"] == "10.50万m3"
    assert fields["excavation_volume"]["normalized_value"] == "10.50"
    assert fields["fill_volume"]["value"] == "8.25万m3"
    assert fields["borrow_volume"]["value"] == "1.00万m3"
    assert fields["spoil_volume"]["value"] == "3.25万m3"


def test_extract_fields_uses_global_offsets_for_non_contiguous_core_chunks():
    project_chunk = _chunk("chunk-0001", "项目名称：测试项目。", "项目概况", char_start=100)
    earthwork_text = "土石方平衡：挖方10.50万m3，填方8.25万m3。"
    earthwork_chunk = _chunk("chunk-0009", earthwork_text, "土石方平衡", char_start=900)

    fields = _by_name(extract_fields([project_chunk, earthwork_chunk]))

    excavation = fields["excavation_volume"]
    assert excavation["section"] == "土石方平衡"
    assert excavation["source_span"] == {
        "char_start": 900 + earthwork_text.index("10.50"),
        "char_end": 900 + earthwork_text.index("10.50") + len("10.50万m3"),
    }


def test_extract_fields_uses_global_offsets_for_keyword_in_second_chunk():
    project_chunk = _chunk("chunk-0001", "项目名称：测试项目。", "项目概况", char_start=100)
    spoil_text = "弃方去向为外运至合规消纳场。"
    spoil_chunk = _chunk("chunk-0008", spoil_text, "土石方平衡", char_start=800)

    fields = _by_name(extract_fields([project_chunk, spoil_chunk]))

    spoil_destination = fields["spoil_destination"]
    assert spoil_destination["value"] == "外运"
    assert spoil_destination["section"] == "土石方平衡"
    assert spoil_destination["source_span"] == {
        "char_start": 800 + spoil_text.index("外运"),
        "char_end": 800 + spoil_text.index("外运") + len("外运"),
    }
