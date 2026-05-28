import json

from app.config import settings
from app.services import rag_service, water_review_service
from app.services.langextract_service import facts_to_extracted_fields
from app.services.mineru_table_fact_service import extract_table_facts
from app.services.water_review_service import ParsedBlock, ReviewChunk


def test_extract_table_facts_reads_earthwork_values_from_mineru_html():
    block = ParsedBlock(
        block_id="p22-table-1",
        page=22,
        bbox=[69, 550, 525, 698],
        text="土石方平衡表",
        type="table",
        section_hint="1.3.2 土石方平衡",
        char_start=100,
        char_end=150,
        html=(
            "<table>"
            "<tr><th>项目</th><th>挖方</th><th>填方</th><th>借方</th><th>弃方</th></tr>"
            "<tr><td>合计</td><td>10.00万m3</td><td>8.00万m3</td><td>2.00万m3</td><td>4.00万m3</td></tr>"
            "</table>"
        ),
    )
    chunk = ReviewChunk(
        chunk_id="chunk-earthwork",
        text="土石方平衡表：挖方10.00万m3，填方8.00万m3，借方2.00万m3，弃方4.00万m3。",
        section="1.3.2 土石方平衡",
        page_range=[22, 22],
        bbox_list=[{"block_id": "p22-table-1", "page": 22, "bbox": [69, 550, 525, 698]}],
        table_refs=["p22-table-1"],
        metadata={"block_ids": ["p22-table-1"]},
        char_start=100,
        char_end=180,
    )

    facts = extract_table_facts([block], [chunk])

    by_field = {fact["field_name"]: fact for fact in facts}
    assert by_field["excavation_volume"]["normalized_value"] == "10.00"
    assert by_field["fill_volume"]["unit"] == "万m3"
    assert by_field["borrow_volume"]["chunk_id"] == "chunk-earthwork"
    assert by_field["spoil_volume"]["block_ids"] == ["p22-table-1"]


def test_extract_table_facts_inherits_unit_from_table_header():
    block = ParsedBlock(
        block_id="p22-table-2",
        page=22,
        bbox=[69, 550, 525, 698],
        text="土石方平衡表",
        type="table",
        section_hint="1.3.2 土石方平衡",
        char_start=100,
        char_end=150,
        html=(
            "<table>"
            "<tr><th>项目</th><th>挖方（万m3）</th><th>填方（万m3）</th><th>借方（万m3）</th><th>弃方（万m3）</th></tr>"
            "<tr><td>合计</td><td>10.00</td><td>8.00</td><td>2.00</td><td>4.00</td></tr>"
            "</table>"
        ),
    )

    facts = extract_table_facts([block], [])

    by_field = {fact["field_name"]: fact for fact in facts}
    assert by_field["excavation_volume"]["value"] == "10.00万m3"
    assert by_field["spoil_volume"]["normalized_value"] == "4.00"


def test_extract_table_facts_keeps_image_only_table_as_non_numeric_evidence():
    block = ParsedBlock(
        block_id="p22-table-image",
        page=22,
        bbox=[69, 550, 525, 698],
        text="https://example.com/table.jpg",
        type="table",
        section_hint="1.3.2 土石方平衡",
        char_start=100,
        char_end=130,
        html="",
        image_path="https://example.com/table.jpg",
    )

    assert extract_table_facts([block], []) == []


def test_table_facts_keep_unit_when_converted_to_extracted_fields():
    fact = {
        "fact_id": "mineru-table-unit",
        "field_name": "excavation_volume",
        "value": "10.00万m3",
        "normalized_value": "10.00",
        "unit": "万m3",
        "section": "1.3.2 土石方平衡",
        "chunk_id": "chunk-earthwork",
        "page_range": [22, 22],
        "source_text": "挖方10.00万m3",
        "char_interval": {"start_pos": 0, "end_pos": 10},
        "confidence": 96,
    }

    fields = facts_to_extracted_fields([fact], [])

    excavation = next(field for field in fields if field["field_name"] == "excavation_volume")
    assert excavation["unit"] == "万m3"


def test_run_pipeline_persists_mineru_table_facts_before_prose_fallback(tmp_path, monkeypatch):
    source = tmp_path / "mineru.json"
    artifact_dir = tmp_path / "artifacts"
    source.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "bbox": [69, 550, 525, 698],
                                "type": "table",
                                "index": 1,
                                "html": (
                                    "<table>"
                                    "<tr><th>项目</th><th>挖方</th><th>填方</th><th>借方</th><th>弃方</th></tr>"
                                    "<tr><td>合计</td><td>10.00万m3</td><td>8.00万m3</td><td>2.00万m3</td><td>4.00万m3</td></tr>"
                                    "</table>"
                                ),
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "langextract_enabled", False)
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda session_id, chunks, rules, artifact_path, facts=None, findings=None: {
            "issues": [],
            "retrievals": [],
            "index_manifest": {"fact_count": len(facts or [])},
        },
    )
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])

    water_review_service.run_pipeline(str(source), str(artifact_dir), "table-session")

    facts = json.loads((artifact_dir / "langextract_facts.json").read_text(encoding="utf-8"))
    fields = json.loads((artifact_dir / "extracted_fields.json").read_text(encoding="utf-8"))
    by_fact = {fact["field_name"]: fact for fact in facts}
    by_field = {field["field_name"]: field for field in fields}
    assert by_fact["excavation_volume"]["attributes"]["source"] == "mineru_table_html"
    assert by_fact["spoil_volume"]["block_ids"] == ["p1-b1"]
    assert by_field["excavation_volume"]["fact_id"].startswith("mineru-table-")
