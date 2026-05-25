from app.services.langextract_service import (
    build_cross_chapter_findings,
    build_fact_index,
    facts_to_extracted_fields,
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
