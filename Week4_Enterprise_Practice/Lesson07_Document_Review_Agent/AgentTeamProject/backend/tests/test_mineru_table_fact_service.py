import json
from dataclasses import asdict

import pytest

from app.config import settings
from app.services import langextract_service
from app.services import rag_service, review_agent_service, review_config_service, water_review_service
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


def test_run_pipeline_skips_external_langextract_in_main_pipeline_by_default(tmp_path, monkeypatch):
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

    monkeypatch.setattr(settings, "langextract_enabled", True)
    monkeypatch.setattr(
        langextract_service,
        "run_langextract",
        lambda *_args, **_kwargs: pytest.fail("LangExtract must not block the main review pipeline by default"),
    )
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
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "main-pipeline-skip-langextract")

    facts = json.loads((artifact_dir / "langextract_facts.json").read_text(encoding="utf-8"))
    status = json.loads((artifact_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    stages = {stage["id"]: stage for stage in status["stages"]}
    assert result["facts"] == facts
    assert len(facts) > 0
    assert stages["langextract_facts"]["status"] == "skipped"
    assert "同步 LangExtract" in stages["langextract_facts"]["message"]
    assert stages["rag_index"]["status"] == "completed"


def test_run_pipeline_persists_langextract_facts_before_rag_failure(tmp_path, monkeypatch):
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
                                "bbox": [69, 120, 525, 168],
                                "type": "text",
                                "index": 1,
                                "lines": [{"spans": [{"content": "项目名称：测试项目。"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fact = {
        "fact_id": "fact-project-001",
        "field_name": "project_name",
        "value": "测试项目",
        "normalized_value": "测试项目",
        "unit": "",
        "section": "综合说明",
        "chunk_id": "chunk-0001",
        "page_range": [1, 1],
        "source_text": "项目名称：测试项目",
        "char_interval": {"start_pos": 0, "end_pos": 9},
        "block_ids": ["p1-b1"],
        "bbox_list": [{"block_id": "p1-b1", "page": 1, "bbox": [69, 120, 525, 168]}],
        "confidence": 92,
        "attributes": {},
    }

    monkeypatch.setattr(settings, "langextract_enabled", True)
    monkeypatch.setattr(settings, "langextract_main_pipeline_enabled", True)
    monkeypatch.setattr(langextract_service, "run_langextract", lambda chunks: [fact])
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])

    def fail_rag(*args, **kwargs):
        raise RuntimeError("rag failed after facts")

    monkeypatch.setattr(rag_service, "run_rag_review", fail_rag)

    with pytest.raises(RuntimeError, match="rag failed after facts"):
        water_review_service.run_pipeline(str(source), str(artifact_dir), "facts-before-rag-failure")

    facts = json.loads((artifact_dir / "langextract_facts.json").read_text(encoding="utf-8"))
    fact_index = json.loads((artifact_dir / "langextract_fact_index.json").read_text(encoding="utf-8"))
    fields = json.loads((artifact_dir / "extracted_fields.json").read_text(encoding="utf-8"))

    assert facts[0]["fact_id"] == "fact-project-001"
    assert fact_index["fact_count"] == 1
    assert next(field for field in fields if field["field_name"] == "project_name")["fact_id"] == "fact-project-001"


def test_run_pipeline_degrades_when_langextract_fails(tmp_path, monkeypatch):
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

    def fail_langextract(_chunks):
        raise langextract_service.LangExtractReviewError("LangExtract document timed out after 45 seconds")

    monkeypatch.setattr(settings, "langextract_enabled", True)
    monkeypatch.setattr(settings, "langextract_main_pipeline_enabled", True)
    monkeypatch.setattr(langextract_service, "run_langextract", fail_langextract)
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
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "langextract-degraded-session")

    facts = json.loads((artifact_dir / "langextract_facts.json").read_text(encoding="utf-8"))
    status = json.loads((artifact_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    stages = {stage["id"]: stage for stage in status["stages"]}
    assert result["facts"] == facts
    assert len(facts) > 0
    assert stages["langextract_facts"]["status"] == "degraded"
    assert "timed out" in stages["langextract_facts"]["message"]
    assert stages["rag_index"]["status"] == "completed"


def test_run_pipeline_reuses_cached_prerag_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    source.write_text("{}", encoding="utf-8")
    block = ParsedBlock(
        block_id="p1-b1",
        page=1,
        bbox=[10, 20, 100, 40],
        text="项目名称：缓存项目。",
        type="text",
        section_hint="综合说明",
        char_start=0,
        char_end=10,
    )
    chunk = ReviewChunk(
        chunk_id="chunk-0001",
        text="项目名称：缓存项目。",
        section="综合说明",
        page_range=[1, 1],
        bbox_list=[{"block_id": "p1-b1", "page": 1, "bbox": [10, 20, 100, 40]}],
        table_refs=[],
        metadata={"block_ids": ["p1-b1"]},
        char_start=0,
        char_end=10,
    )
    fields = [
        {
            "field_name": "project_name",
            "value": "缓存项目",
            "confidence": 92,
            "source_span": {"page": 1, "text": "项目名称：缓存项目。"},
        }
    ]
    facts = [
        {
            "fact_id": "fact-project-cache",
            "field_name": "project_name",
            "value": "缓存项目",
            "chunk_id": "chunk-0001",
            "page_range": [1, 1],
            "confidence": 92,
        }
    ]
    (artifact_dir / "parsed_blocks.json").write_text(json.dumps([asdict(block)], ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "review_chunks.json").write_text(json.dumps([asdict(chunk)], ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "extracted_fields.json").write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "langextract_facts.json").write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "langextract_fact_index.json").write_text(
        json.dumps({"fact_count": 1, "fields": ["project_name"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "cross_chapter_findings.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(settings, "langextract_enabled", True)
    monkeypatch.setattr(water_review_service, "parse_document", lambda *_args, **_kwargs: pytest.fail("parse should use cache"))
    monkeypatch.setattr(water_review_service, "build_chunks", lambda *_args, **_kwargs: pytest.fail("chunking should use cache"))
    monkeypatch.setattr(water_review_service, "extract_fields", lambda *_args, **_kwargs: pytest.fail("field extraction should use cache"))
    monkeypatch.setattr(water_review_service, "extract_table_facts", lambda *_args, **_kwargs: pytest.fail("table extraction should use cache"))
    monkeypatch.setattr(langextract_service, "run_langextract", lambda *_args, **_kwargs: pytest.fail("LangExtract should use cache"))
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda session_id, chunks, rules, artifact_path, facts=None, findings=None: {
            "issues": [],
            "retrievals": [],
            "index_manifest": {"fact_count": len(facts or [])},
            "cache_hits": {"rag_retrievals": True, "rag_issues": True},
        },
    )
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "cached-prerag-session")

    assert result["fields"] == fields
    assert result["facts"] == facts
    assert result["cache_hits"]["parsed_blocks"] is True
    assert result["cache_hits"]["review_chunks"] is True
    assert result["cache_hits"]["prerag_artifacts"] is True
    status = json.loads((artifact_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    by_id = {stage["id"]: stage for stage in status["stages"]}
    assert by_id["parsed_blocks"]["status"] == "cached"
    assert by_id["langextract_facts"]["status"] == "cached"


def test_run_pipeline_invalidates_cache_when_source_signature_changes(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    source.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "bbox": [69, 120, 525, 168],
                                "type": "text",
                                "index": 1,
                                "lines": [{"spans": [{"content": "项目名称：新项目。"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    old_block = ParsedBlock(
        block_id="p1-old",
        page=1,
        bbox=[],
        text="项目名称：旧项目。",
        type="text",
        section_hint="综合说明",
        char_start=0,
        char_end=10,
    )
    (artifact_dir / "parsed_blocks.json").write_text(json.dumps([asdict(old_block)], ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "pipeline_status.json").write_text(
        json.dumps({"source_signature": {"path": "old-source.json", "exists": True}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "langextract_enabled", False)
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda session_id, chunks, rules, artifact_path, facts=None, findings=None: {
            "issues": [],
            "retrievals": [],
            "index_manifest": {},
            "cache_hits": {"rag_retrievals": False, "rag_issues": False},
        },
    )
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [])

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "changed-source-session")

    assert result["cache_hits"]["parsed_blocks"] is False
    assert result["blocks"][0].text == "项目名称：新项目。"
    status = json.loads((artifact_dir / "pipeline_status.json").read_text(encoding="utf-8"))
    assert status["source_signature"]["path"] == str(source.resolve())


def test_run_pipeline_reviews_configured_check_items_with_rag_evidence_store(tmp_path, monkeypatch):
    source = tmp_path / "mineru.json"
    artifact_dir = tmp_path / "artifacts"
    vector_dir = tmp_path / "vectors"
    source.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "bbox": [69, 120, 525, 168],
                                "type": "text",
                                "index": 1,
                                "lines": [{"spans": [{"content": "项目概况：建设内容包括住宅楼和地下车库。"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = object()
    captured: dict[str, object] = {}

    def fake_build_evidence_slot_package(check_item, chunks, passed_store, **kwargs):
        captured["store"] = passed_store
        captured["use_rerank"] = kwargs.get("use_rerank")
        return {
            "source": "evidence_slots",
            "missing_required_slot_ids": ["approval_or_design_content"],
            "slots": [],
        }

    monkeypatch.setattr(settings, "langextract_enabled", False)
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda session_id, chunks, rules, artifact_path, facts=None, findings=None: {
            "issues": [],
            "retrievals": [],
            "index_manifest": {"vector_store": str(vector_dir)},
        },
    )
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])
    monkeypatch.setattr(water_review_service, "_pipeline_evidence_store", lambda session_id, rag_result: store)
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [
        {
            "rule_id": "PROJECT-COMPOSITION-PIPELINE-001",
            "rule_name": "项目组成及建设内容一致性",
            "category": "项目组成一致性",
            "evidence_slots": [
                {
                    "id": "approval_or_design_content",
                    "label": "立项或主体设计建设内容",
                    "required": True,
                    "queries": ["立项文件 主体设计 建设内容"],
                }
            ],
        }
    ])
    monkeypatch.setattr(review_agent_service, "build_evidence_slot_package", fake_build_evidence_slot_package)

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "pipeline-store-session")

    assert captured == {"store": store, "use_rerank": True}
    assert any(item["ai_finding"].startswith("项目组成及建设内容一致性") for item in result["review_items"])


def test_run_pipeline_reviews_configured_check_items_without_rag_evidence_store(tmp_path, monkeypatch):
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
                                "bbox": [69, 120, 525, 168],
                                "type": "text",
                                "index": 1,
                                "lines": [{"spans": [{"content": "项目概况：建设内容包括住宅楼和地下车库。"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_build_evidence_slot_package(check_item, chunks, passed_store, **kwargs):
        captured["store"] = passed_store
        captured["use_rerank"] = kwargs.get("use_rerank")
        return {
            "source": "evidence_slots",
            "missing_required_slot_ids": ["approval_or_design_content"],
            "slots": [],
        }

    monkeypatch.setattr(settings, "langextract_enabled", False)
    monkeypatch.setattr(
        rag_service,
        "run_rag_review",
        lambda session_id, chunks, rules, artifact_path, facts=None, findings=None: {
            "issues": [],
            "retrievals": [],
            "index_manifest": {},
        },
    )
    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [])
    monkeypatch.setattr(review_config_service, "list_check_item_specs", lambda: [
        {
            "rule_id": "PROJECT-COMPOSITION-PIPELINE-DEGRADED",
            "rule_name": "项目组成及建设内容一致性",
            "category": "项目组成一致性",
            "evidence_slots": [
                {
                    "id": "approval_or_design_content",
                    "label": "立项或主体设计建设内容",
                    "required": True,
                    "queries": ["立项文件 主体设计 建设内容"],
                }
            ],
        }
    ])
    monkeypatch.setattr(review_agent_service, "build_evidence_slot_package", fake_build_evidence_slot_package)

    result = water_review_service.run_pipeline(str(source), str(artifact_dir), "pipeline-no-store-session")

    assert captured == {"store": None, "use_rerank": False}
    issue = next(item for item in result["review_items"] if item["ai_finding"].startswith("项目组成及建设内容一致性"))
    reasoning = json.loads(issue["ai_reasoning"])
    assert reasoning["retrieval_trace"]["requested_store"] is False
