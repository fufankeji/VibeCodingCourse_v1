from app.services.review_executor_service import execute_check_item_precheck
from app.services.review_rule_schema import build_review_rule_topics


def test_evidence_presence_reports_scope_and_text_coverage():
    check_item = {
        "id": "evidence-1",
        "executor_type_id": "evidence_presence",
        "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
        "target_fields": ["乔木", "灌木"],
        "regulation_clauses": ["条款 A"],
    }

    result_without_evidence = execute_check_item_precheck(check_item)

    assert result_without_evidence["executor_type_id"] == "evidence_presence"
    assert result_without_evidence["handler_id"] == "evidence_presence"
    assert result_without_evidence["execution_status"] == "needs_review"
    assert any(check["type"] == "evidence_text_presence" for check in result_without_evidence["checks"])
    assert any("未提供" in check.get("reason", "") for check in result_without_evidence["checks"])

    result_with_evidence = execute_check_item_precheck(
        check_item,
        evidence_bundle={"evidence_texts": ["植物措施章节列明乔木、灌木配置，附植物措施工程量表。"]},
    )

    assert result_with_evidence["execution_status"] == "pass"
    assert result_with_evidence["checks"][0]["status"] == "pass"
    assert result_with_evidence["checks"][1]["status"] == "pass"
    assert result_with_evidence["target_fields"] == ["乔木", "灌木"]
    assert result_with_evidence["regulation_clauses"] == ["条款 A"]


def test_evidence_presence_reports_missing_scope_explainably():
    result = execute_check_item_precheck(
        {"id": "evidence-no-scope", "executor_type_id": "evidence_presence"},
        evidence_bundle={"evidence_texts": ["已有证据文本，但配置项未声明证据范围。"]},
    )

    assert result["execution_status"] == "needs_review"
    assert result["checks"][0]["type"] == "evidence_scope_configured"
    assert result["checks"][0]["status"] == "needs_review"
    assert "未配置" in result["checks"][0]["reason"]


def test_unknown_executor_falls_back_to_manual_basic_and_preserves_executor_id():
    result = execute_check_item_precheck(
        {
            "id": "custom-1",
            "executor_type_id": "topic_specific_executor",
            "target_fields": ["占地面积"],
        }
    )

    assert result["executor_type_id"] == "topic_specific_executor"
    assert result["handler_id"] == "manual_basic"
    assert result["execution_status"] == "pending"
    assert result["llm_required"] is True
    assert result["checks"][0]["type"] == "manual_review_required"


def test_configured_check_item_reasoning_process_contains_executor_precheck():
    topics = build_review_rule_topics(
        [],
        configured_check_items=[
            {
                "id": "configured-plant-1",
                "topic_id": "scmc-010",
                "executor_type_id": "custom_executor",
                "review_type": "自定义执行器",
                "review_sub_type": "植物措施配置审查",
                "target_fields": ["植物措施"],
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")
    item = next(item for item in plant["check_items"] if item["id"] == "configured-plant-1")

    assert item["status"] == "pending"
    assert item["reasoning_process"]["mode"] == "configurable_review_item"
    precheck = item["reasoning_process"]["executor_precheck"]
    assert precheck["executor_type_id"] == "custom_executor"
    assert precheck["handler_id"] == "manual_basic"
    assert precheck["execution_status"] == "pending"


def test_disabled_configured_item_has_disabled_executor_result():
    topics = build_review_rule_topics(
        [],
        configured_check_items=[
            {
                "id": "disabled-custom",
                "topic_id": "scmc-010",
                "executor_type_id": "evidence_presence",
                "review_type": "证据存在性核验",
                "review_sub_type": "停用审查项",
                "enabled": False,
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")
    item = next(item for item in plant["check_items"] if item["id"] == "disabled-custom")
    precheck = item["reasoning_process"]["executor_precheck"]

    assert item["status"] == "disabled"
    assert precheck["executor_type_id"] == "evidence_presence"
    assert precheck["handler_id"] == "evidence_presence"
    assert precheck["execution_status"] == "disabled"
    assert precheck["llm_required"] is False
