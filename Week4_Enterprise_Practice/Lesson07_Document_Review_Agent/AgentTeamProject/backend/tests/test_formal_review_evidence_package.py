import json

import pytest

from app.schemas.item import ReviewItemResponse
from app.services import review_agent_service
from app.services.langextract_service import facts_to_extracted_fields
from app.services.mineru_table_fact_service import extract_table_facts
from app.services.water_review_service import ReviewChunk, WATER_FIELDS, review_rules
from app.services.water_review_service import ParsedBlock


def _chunk(chunk_id: str, text: str, section: str = "1 项目概况") -> ReviewChunk:
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[1, 1],
        bbox_list=[{"block_id": f"{chunk_id}-b1", "page": 1, "bbox": [10, 20, 100, 40]}],
        table_refs=[],
        metadata={"block_type": "text"},
        char_start=0,
        char_end=len(text),
    )


def _empty_fields() -> list[dict]:
    return [{"field_name": name, "value": "", "normalized_value": "", "unit": ""} for name in WATER_FIELDS]


def _field(field_name: str, value: str, unit: str = "万m3") -> dict:
    return {
        "field_name": field_name,
        "value": value,
        "normalized_value": value,
        "unit": unit,
        "chunk_id": "earthwork",
        "page_range": [1, 1],
        "source_text": f"{field_name}={value}{unit}",
        "confidence": 90,
    }


def test_evidence_slot_package_uses_shared_candidate_top_k_default(monkeypatch: pytest.MonkeyPatch):
    captured_top_k: list[int] = []

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        captured_top_k.append(top_k)
        return {
            "query": query,
            "retrieval_mode": "fake",
            "matches": [
                {
                    "chunk_id": f"slot-candidate-{index}",
                    "document": f"植物措施 乔木 灌木 第 {index} 条证据",
                    "metadata": {"page_start": index, "page_end": index, "section": "植物措施"},
                    "score": 1.0 / index,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": index},
                }
                for index in range(1, 8)
            ],
        }

    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)

    package = review_agent_service.build_evidence_slot_package(
        {
            "evidence_slots": [
                {
                    "id": "plant_slot",
                    "required": True,
                    "queries": ["植物措施 乔木 灌木"],
                }
            ]
        },
        [_chunk("plant", "植物措施：乔木120株、灌木800株。")],
        store=None,
    )

    slot = package["slots"][0]
    assert captured_top_k == [50]
    assert slot["candidate_top_k"] == 50
    assert slot["final_match_limit"] == 5
    assert slot["match_count"] == 5
    assert slot["prompt_match_limit"] == 3
    assert slot["min_matches"] == 1
    assert [match["chunk_id"] for match in slot["prompt_matches"]] == [
        "slot-candidate-1",
        "slot-candidate-2",
        "slot-candidate-3",
    ]
    assert [match["chunk_id"] for match in slot["trace_matches"]] == [
        "slot-candidate-4",
        "slot-candidate-5",
    ]
    assert [match["chunk_id"] for match in slot["matches"]] == [
        "slot-candidate-1",
        "slot-candidate-2",
        "slot-candidate-3",
        "slot-candidate-4",
        "slot-candidate-5",
    ]


def test_formal_review_configured_check_item_blocks_when_required_evidence_slot_is_missing():
    issues = review_rules(
        "slot-session",
        [_chunk("project-overview", "项目概况：建设内容包括住宅楼和地下车库。")],
        _empty_fields(),
        [
            {
                "rule_id": "PROJECT-COMPOSITION-001",
                "rule_name": "项目组成及建设内容一致性",
                "category": "项目组成一致性",
                "target_fields": ["建设内容"],
                "evidence_requirement": "项目概况与立项文件或主体设计文件应一致。",
                "evidence_slots": [
                    {
                        "id": "project_overview_content",
                        "label": "项目概况建设内容",
                        "required": True,
                        "queries": ["项目概况 建设内容"],
                    },
                    {
                        "id": "approval_or_design_content",
                        "label": "立项或主体设计建设内容",
                        "required": True,
                        "queries": ["立项文件 主体设计 建设内容"],
                        "expected_terms": ["立项文件"],
                    },
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("项目组成及建设内容一致性"))
    reasoning = json.loads(issue["ai_reasoning"])

    assert reasoning["review_status"] == "needs_evidence"
    assert reasoning["evidence_slot_package"]["missing_required_slot_ids"] == ["approval_or_design_content"]
    assert reasoning["evidence_slot_package"]["slots"][0]["status"] == "matched"
    assert reasoning["evidence_slot_package"]["slots"][1]["status"] == "missing"


def test_formal_review_flags_project_composition_mismatch():
    chunks = [
        _chunk(
            "project-body",
            "1.1 项目概况 建设内容：项目建设内容包括住宅楼、地下车库。建设规模：总建筑面积81700.84平方米，其中地上建筑面积53250平方米，地下建筑面积28450.84平方米。",
            section="1.1 项目概况",
        ),
        _chunk(
            "project-approval",
            "附件 初步设计批复：核定项目建筑面积为80836.65平方米，其中地上建筑面积53250平方米，地下建筑面积27586.65平方米。",
            section="附件4 初步设计批复",
        ),
    ]
    issues = review_rules(
        "project-composition-mismatch-session",
        chunks,
        _empty_fields(),
        [
            {
                "rule_id": "PROJECT-COMPOSITION-MISMATCH-001",
                "rule_name": "项目组成及建设内容一致性",
                "category": "项目组成一致性",
                "review_type": "项目组成一致性审查",
                "review_sub_type": "项目组成及建设内容应与立项文件或主体设计文件一致",
                "target_fields": ["项目组成", "建设内容"],
                "evidence_slots": [
                    {
                        "id": "project_overview_content",
                        "label": "项目概要建设内容",
                        "required": True,
                        "queries": ["项目概况 建设内容 总建筑面积 地上建筑面积 地下建筑面积"],
                    },
                    {
                        "id": "approval_or_design_content",
                        "label": "立项或主体设计建设内容",
                        "required": True,
                        "queries": ["初步设计批复 项目建筑面积 地上建筑面积 地下建筑面积"],
                    },
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("项目组成及建设内容一致性"))
    reasoning = json.loads(issue["ai_reasoning"])

    assert reasoning["project_composition_consistency"]["status"] == "mismatch"
    assert reasoning["review_status"] == "issue"
    assert "项目组成一致性不通过" in issue["ai_finding"]


def test_formal_review_structured_issue_reuses_available_store_with_rerank(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}
    store = object()

    def fake_build_evidence_slot_package(check_item, chunks, passed_store, **kwargs):
        captured["store"] = passed_store
        captured["use_rerank"] = kwargs.get("use_rerank")
        return {
            "source": "evidence_slots",
            "missing_required_slot_ids": ["approval_or_design_content"],
            "slots": [
                {
                    "slot_id": "approval_or_design_content",
                    "required": True,
                    "status": "missing",
                    "matches": [],
                }
            ],
        }

    monkeypatch.setattr(review_agent_service, "build_evidence_slot_package", fake_build_evidence_slot_package)

    issues = review_rules(
        "slot-vector-session",
        [_chunk("project-overview", "项目概况：建设内容包括住宅楼和地下车库。")],
        _empty_fields(),
        [
            {
                "rule_id": "PROJECT-COMPOSITION-VECTOR-001",
                "rule_name": "项目组成及建设内容一致性",
                "category": "项目组成一致性",
                "evidence_slots": [
                    {
                        "id": "approval_or_design_content",
                        "label": "立项或主体设计建设内容",
                        "required": True,
                        "queries": ["立项文件 主体设计 建设内容"],
                        "expected_terms": ["立项文件"],
                    }
                ],
            }
        ],
        evidence_store=store,
    )

    assert captured == {"store": store, "use_rerank": True}
    issue = next(item for item in issues if item["ai_finding"].startswith("项目组成及建设内容一致性"))
    reasoning = json.loads(issue["ai_reasoning"])
    assert reasoning["evidence_slot_package"]["missing_required_slot_ids"] == ["approval_or_design_content"]


def test_formal_review_structured_issue_falls_back_when_store_is_unavailable():
    class UnavailableStore:
        def query(self, query, top_k):
            raise RuntimeError("vector store unavailable")

    issues = review_rules(
        "slot-unavailable-store-session",
        [_chunk("project-overview", "项目概况：建设内容包括住宅楼和地下车库。")],
        _empty_fields(),
        [
            {
                "rule_id": "PROJECT-COMPOSITION-DEGRADED-001",
                "rule_name": "项目组成及建设内容一致性",
                "category": "项目组成一致性",
                "evidence_slots": [
                    {
                        "id": "approval_or_design_content",
                        "label": "立项或主体设计建设内容",
                        "required": True,
                        "queries": ["立项文件 主体设计 建设内容"],
                        "expected_terms": ["立项文件"],
                    }
                ],
            }
        ],
        evidence_store=UnavailableStore(),
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("项目组成及建设内容一致性"))
    reasoning = json.loads(issue["ai_reasoning"])
    assert reasoning["review_status"] == "needs_evidence"
    assert reasoning["retrieval_trace"] == {
        "requested_store": True,
        "used_store": False,
        "degraded": True,
        "reason_type": "vector_retrieval_failed",
    }
    assert reasoning["evidence_slot_package"]["missing_required_slot_ids"] == ["approval_or_design_content"]


def test_formal_review_structured_issue_does_not_swallow_non_vector_rag_error(monkeypatch: pytest.MonkeyPatch):
    from app.services.rag_service import RAGReviewError

    store = object()
    calls: list[object] = []

    def fake_build_evidence_slot_package(check_item, chunks, passed_store, **kwargs):
        calls.append(passed_store)
        if len(calls) == 1:
            raise RAGReviewError("SiliconFlow reranker response shape is invalid")
        return {
            "source": "evidence_slots",
            "missing_required_slot_ids": ["approval_or_design_content"],
            "slots": [],
        }

    monkeypatch.setattr(review_agent_service, "build_evidence_slot_package", fake_build_evidence_slot_package)

    with pytest.raises(RAGReviewError, match="reranker"):
        review_rules(
            "slot-rerank-error-session",
            [_chunk("project-overview", "项目概况：建设内容包括住宅楼和地下车库。")],
            _empty_fields(),
            [
                {
                    "rule_id": "PROJECT-COMPOSITION-RERANK-ERROR",
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
            ],
            evidence_store=store,
        )
    assert calls == [store]


def test_formal_review_configured_formula_missing_fields_is_needs_evidence():
    fields = [
        *_empty_fields(),
        _field("excavation_volume", "10"),
        _field("fill_volume", "8"),
    ]

    issues = review_rules(
        "formula-session",
        [_chunk("earthwork", "土石方平衡：挖方10万m3，填方8万m3。", section="1.3.2 土石方平衡")],
        fields,
        [
            {
                "rule_id": "EARTHWORK-001",
                "rule_name": "土石方平衡完整性",
                "category": "土石方平衡",
                "formula_checks": [
                    {
                        "id": "earthwork_total_balance",
                        "left_fields": ["excavation_volume", "borrow_volume"],
                        "right_fields": ["fill_volume", "spoil_volume"],
                        "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    }
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("土石方平衡完整性"))
    reasoning = json.loads(issue["ai_reasoning"])

    assert reasoning["review_status"] == "needs_evidence"
    assert reasoning["formula_check_results"]["checks"][0]["status"] == "missing"
    assert reasoning["formula_check_results"]["checks"][0]["missing_fields"] == ["borrow_volume", "spoil_volume"]


def test_formal_review_configured_formula_failure_is_issue():
    fields = [
        *_empty_fields(),
        _field("excavation_volume", "10"),
        _field("fill_volume", "8"),
        _field("borrow_volume", "1"),
        _field("spoil_volume", "4"),
        _field("borrow_area", "商品土来源", unit=""),
        _field("spoil_destination", "外运综合利用", unit=""),
        _field("comprehensive_utilization", "场内调配后外运综合利用", unit=""),
    ]

    issues = review_rules(
        "formula-fail-session",
        [_chunk("earthwork", "土石方平衡：挖方10万m3，填方8万m3，借方1万m3，弃方4万m3。", section="1.3.2 土石方平衡")],
        fields,
        [
            {
                "rule_id": "EARTHWORK-FAIL-001",
                "rule_name": "土石方平衡公式复核",
                "category": "土石方平衡",
                "formula_checks": [
                    {
                        "id": "earthwork_total_balance",
                        "left_fields": ["excavation_volume", "borrow_volume"],
                        "right_fields": ["fill_volume", "spoil_volume"],
                        "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    }
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("土石方平衡公式复核"))
    reasoning = json.loads(issue["ai_reasoning"])

    assert reasoning["review_status"] == "issue"
    assert reasoning["formula_check_results"]["checks"][0]["status"] == "fail"


def test_formal_review_formula_failure_stays_issue_when_earthwork_audit_is_missing():
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
            "<tr><th>项目</th><th>挖方（万m3）</th><th>填方（万m3）</th><th>借方（万m3）</th><th>弃方（万m3）</th></tr>"
            "<tr><td>合计</td><td>10.00</td><td>8.00</td><td>1.00</td><td>4.00</td></tr>"
            "</table>"
        ),
    )
    chunk = _chunk("earthwork-table", "土石方平衡表", section="1.3.2 土石方平衡")
    chunk.table_refs = ["p22-table-1"]
    table_facts = extract_table_facts([block], [chunk])
    fields = facts_to_extracted_fields(table_facts, _empty_fields())

    issues = review_rules(
        "formula-table-fail-session",
        [chunk],
        fields,
        [
            {
                "rule_id": "EARTHWORK-TABLE-FAIL-001",
                "rule_name": "土石方平衡表公式复核",
                "category": "土石方平衡",
                "formula_checks": [
                    {
                        "id": "earthwork_total_balance",
                        "left_fields": ["excavation_volume", "borrow_volume"],
                        "right_fields": ["fill_volume", "spoil_volume"],
                        "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    }
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("土石方平衡表公式复核"))
    reasoning = json.loads(issue["ai_reasoning"])

    assert reasoning["formula_check_results"]["checks"][0]["status"] == "fail"
    assert reasoning["earthwork_audit_results"]["status"] == "needs_evidence"
    assert reasoning["review_status"] == "issue"
    assert "公式校验未通过" in issue["ai_finding"]


def test_formal_review_earthwork_audit_blocks_missing_borrow_source_and_spoil_destination():
    fields = [
        *_empty_fields(),
        _field("excavation_volume", "10"),
        _field("fill_volume", "8"),
        _field("borrow_volume", "2"),
        _field("spoil_volume", "4"),
    ]

    issues = review_rules(
        "earthwork-audit-session",
        [_chunk("earthwork", "土石方平衡：挖方10万m3，填方8万m3，借方2万m3，弃方4万m3。", section="1.3.2 土石方平衡")],
        fields,
        [
            {
                "rule_id": "EARTHWORK-AUDIT-001",
                "rule_name": "土石方平衡（含表土）完整性",
                "category": "土石方平衡",
                "formula_checks": [
                    {
                        "id": "earthwork_total_balance",
                        "left_fields": ["excavation_volume", "borrow_volume"],
                        "right_fields": ["fill_volume", "spoil_volume"],
                        "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    }
                ],
            }
        ],
    )

    issue = next(item for item in issues if item["ai_finding"].startswith("土石方平衡（含表土）完整性"))
    reasoning = json.loads(issue["ai_reasoning"])
    missing_audits = [
        check["audit_check_id"]
        for check in reasoning["earthwork_audit_results"]["checks"]
        if check["status"] == "missing"
    ]

    assert reasoning["review_status"] == "needs_evidence"
    assert "土石方结构化审计缺项" in issue["ai_finding"]
    assert reasoning["formula_check_results"]["checks"][0]["status"] == "pass"
    assert "borrow_source" in missing_audits
    assert "spoil_destination" in missing_audits


def test_review_item_response_exposes_structured_review_payloads():
    class Row:
        id = "item-structured"
        session_id = "session-structured"
        clause_text = "土石方平衡证据"
        page_number = 12
        paragraph_index = 0
        highlight_anchor = "chunk-1"
        char_offset_start = 0
        char_offset_end = 8
        risk_level = "HIGH"
        confidence_score = 76
        source_type = "rule_engine"
        risk_category = "土石方专项审查"
        ai_finding = "土石方平衡：公式校验未通过。"
        ai_reasoning = json.dumps(
            {
                "evidence_slot_package": {
                    "source": "evidence_slots",
                    "missing_required_slot_ids": ["topsoil_balance"],
                },
                "formula_check_results": {
                    "source": "formula_checks",
                    "checks": [{"formula_check_id": "earthwork_total_balance", "status": "fail"}],
                },
                "earthwork_audit_results": {
                    "source": "earthwork_audit",
                    "checks": [{"audit_check_id": "borrow_source", "status": "missing"}],
                },
                "project_composition_consistency": {
                    "status": "mismatch",
                    "field_comparisons": [{"field": "total_building_area", "status": "mismatch"}],
                },
                "review_status": "needs_evidence",
                "conclusion_type": "needs_evidence",
            },
            ensure_ascii=False,
        )
        suggested_revision = "补齐证据后复核。"
        human_decision = "pending"
        human_note = None
        human_edited_risk_level = None
        human_edited_finding = None
        is_false_positive = False
        decided_by = None
        decided_at = None
        created_at = "2026-05-29T00:00:00"
        updated_at = "2026-05-29T00:00:00"

    data = ReviewItemResponse.model_validate(Row()).model_dump()

    assert data["evidence_slot_package"]["missing_required_slot_ids"] == ["topsoil_balance"]
    assert data["formula_check_results"]["checks"][0]["formula_check_id"] == "earthwork_total_balance"
    assert data["earthwork_audit_results"]["checks"][0]["audit_check_id"] == "borrow_source"
    assert data["project_composition_consistency"]["status"] == "mismatch"
    assert data["review_status"] == "needs_evidence"
