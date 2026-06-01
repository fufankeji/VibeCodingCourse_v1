from app.services.langextract_service import (
    FIELD_ORDER,
    LANGEXTRACT_ALLOWED_FIELDS,
    build_cross_chapter_findings,
    build_fact_index,
    facts_to_extracted_fields,
    _fact_from_extraction,
)


def _fact(
    field_name: str,
    value: str,
    normalized_value: str,
    unit: str,
    fact_id: str,
    section: str = "项目概况",
    page: int = 1,
):
    return {
        "fact_id": fact_id,
        "field_name": field_name,
        "value": value,
        "normalized_value": normalized_value,
        "unit": unit,
        "section": section,
        "chunk_id": f"chunk-{page:04d}",
        "page_range": [page, page],
        "source_text": f"{field_name}：{value}",
        "char_interval": {"start_pos": 10 * page, "end_pos": 10 * page + len(value)},
        "block_ids": [f"p{page}-b1"],
        "bbox_list": [{"block_id": f"p{page}-b1", "page": page, "bbox": [0, 0, 10, 10]}],
        "confidence": 88,
        "attributes": {},
    }


class _Extraction:
    def __init__(self, extraction_class: str, extraction_text: str):
        self.extraction_class = extraction_class
        self.extraction_text = extraction_text
        self.attributes = {"confidence": "90"}
        self.char_interval = None


class _Chunk:
    text = "施工前对可剥离表土进行剥离，集中堆存在临时堆土区。"
    section = "表土"
    chunk_id = "chunk-topsoil"
    page_range = [8, 8]
    char_start = 0
    bbox_list = []


def test_langextract_allowed_fields_only_contains_core_extraction_fields():
    assert LANGEXTRACT_ALLOWED_FIELDS == (
        "project_name",
        "construction_unit",
        "construction_location",
        "project_nature",
        "land_area",
        "disturbed_area",
        "prevention_responsibility_area",
        "excavation_volume",
        "fill_volume",
        "borrow_volume",
        "spoil_volume",
        "spoil_destination",
        "borrow_area",
        "comprehensive_utilization",
    )
    assert "topsoil_stripping" in FIELD_ORDER
    assert "topsoil_stripping" not in LANGEXTRACT_ALLOWED_FIELDS


def test_facts_to_extracted_fields_ignores_non_core_langextract_fact():
    fact = _fact_from_extraction(_Extraction("topsoil_stripping", "表土进行剥离"), _Chunk(), 0)

    fields = facts_to_extracted_fields([fact] if fact else [], [])
    by_name = {field["field_name"]: field for field in fields}

    assert fact is None
    assert len(fields) == len(FIELD_ORDER)
    assert by_name["topsoil_stripping"]["value"] == ""
    assert by_name["topsoil_stripping"]["extraction_status"] == "not_targeted"
    assert by_name["monitoring"]["value"] == ""
    assert by_name["monitoring"]["extraction_status"] == "not_targeted"
    assert by_name["borrow_volume"]["value"] == ""
    assert by_name["borrow_volume"]["extraction_status"] == "not_found"


def test_facts_to_extracted_fields_prefers_langextract_fact():
    fallback = [
        {
            "field_name": "project_name",
            "value": "旧项目名称",
            "normalized_value": "旧项目名称",
            "source_span": None,
            "section": "",
            "confidence": 55,
        }
    ]
    facts = [_fact("project_name", "北京航空航天大学沙河校区图书馆项目", "北京航空航天大学沙河校区图书馆项目", "", "fact-project")]

    fields = facts_to_extracted_fields(facts, fallback)
    project = next(field for field in fields if field["field_name"] == "project_name")

    assert project["value"] == "北京航空航天大学沙河校区图书馆项目"
    assert project["fact_id"] == "fact-project"
    assert project["source_page_number"] == 1
    assert project["extraction_status"] == "found"


def test_build_fact_index_groups_by_field():
    facts = [
        _fact("disturbed_area", "1.20hm²", "1.2", "hm²", "fact-area-1"),
        _fact("disturbed_area", "1.30hm²", "1.3", "hm²", "fact-area-2"),
    ]

    index = build_fact_index(facts)

    assert index["fact_count"] == 2
    assert index["by_field"]["disturbed_area"] == ["fact-area-1", "fact-area-2"]


def test_cross_chapter_area_conflict_generates_finding():
    facts = [
        _fact("disturbed_area", "1.20hm²", "1.2", "hm²", "fact-disturbed", "项目概况", 5),
        _fact("prevention_responsibility_area", "1.50hm²", "1.5", "hm²", "fact-responsibility", "防治责任范围", 22),
    ]

    findings = build_cross_chapter_findings(facts)

    assert any(finding["finding_type"] == "area_cross_chapter_conflict" for finding in findings)
    assert any({"fact-disturbed", "fact-responsibility"}.issubset(set(finding["fact_ids"])) for finding in findings)


def test_earthwork_balance_conflict_generates_high_risk_finding():
    facts = [
        _fact("excavation_volume", "10.00万m³", "10", "万m³", "fact-excavation", "土石方", 30),
        _fact("fill_volume", "8.00万m³", "8", "万m³", "fact-fill", "土石方", 31),
        _fact("borrow_volume", "0.00万m³", "0", "万m³", "fact-borrow", "土石方", 31),
        _fact("spoil_volume", "1.00万m³", "1", "万m³", "fact-spoil", "土石方", 31),
    ]

    findings = build_cross_chapter_findings(facts)

    balance = next(finding for finding in findings if finding["finding_type"] == "earthwork_balance_conflict")
    assert balance["risk_level"] == "HIGH"
    assert "挖方+借方" in balance["actual_value"]
