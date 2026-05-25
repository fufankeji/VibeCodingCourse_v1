from app.services.review_rule_schema import (
    build_review_rule_topics,
    execute_rule_precheck,
    normalize_review_rule,
)


def test_normalize_review_rule_adds_hierarchy_scope_and_execution():
    rule = {
        "rule_id": "WSB-GEN-005",
        "rule_name": "土石方与表土平衡审查",
        "category": "项目概况类",
        "target_fields": ["挖方", "填方", "借方", "弃方", "表土平衡"],
        "severity_policy": "关键支撑文件、数据或责任界定缺失时判定为重大问题。",
        "evidence_requirement": "需提供土石方平衡表、表土平衡表及弃方去向。",
    }

    enriched = normalize_review_rule(rule)

    assert enriched["review_topic"]["name"] == "土石方总量"
    assert enriched["review_item"]["name"] == "土石方与表土平衡"
    logic_types = {item["type"] for item in enriched["review_logic"]}
    assert "content_review" in logic_types
    assert "consistency_review" in logic_types
    assert "table_calculation_review" in logic_types
    assert "土石方平衡表/表土平衡表" in enriched["evidence_scope"]["tables"]
    assert enriched["rule_execution"]["mode"] == "deterministic_precheck_then_llm_adjudication"


def test_build_review_rule_topics_builds_scmc_topic_checklist():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "A",
                "rule_name": "项目组成一致性审查",
                "category": "项目概况类",
                "target_fields": ["项目组成"],
                "evidence_requirement": "需核验项目组成。",
            },
            {
                "rule_id": "B",
                "rule_name": "监测点位审查",
                "category": "监测类",
                "target_fields": ["监测点位"],
                "evidence_requirement": "需核验监测点位。",
            },
        ]
    )

    topic_names = {topic["topic_name"] for topic in topics}
    assert "工程占地" in topic_names
    assert "综合监测点位、工程措施监测点位、土壤流失量监测点位" in topic_names
    assert len(topics) == 20
    engineering_land = next(topic for topic in topics if topic["name"] == "工程占地")
    assert engineering_land["check_item_count"] == 14
    assert engineering_land["check_items"]
    assert {"id", "review_type", "review_sub_type", "status", "evidence_texts"} <= set(engineering_land["check_items"][0])


def test_build_review_rule_topics_maps_issue_to_check_item():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "WSB-GEN-027",
                "rule_name": "投资概算编制原则审查",
                "category": "投资估算与效益类",
                "target_fields": ["价格水平年", "费用构成"],
                "evidence_requirement": "需核验投资概算编制原则。",
            }
        ],
        [
            {
                "id": "issue-1",
                "risk_category": "投资估算与效益类",
                "risk_level": "HIGH",
                "source_type": "hybrid",
                "ai_finding": "项目总投资前后不一致。",
                "ai_reasoning": '{"rule_id":"WSB-GEN-027","rule_name":"投资概算编制原则审查","rule_source":"审查要点"}',
                "clause_text": "总投资为100万元。",
                "page_number": 12,
                "paragraph_index": 3,
                "highlight_anchor": "chunk-1",
                "human_decision": "pending",
            }
        ],
    )

    investment = next(topic for topic in topics if topic["name"] == "项目总投资")
    assert investment["check_status"] == "failed"
    assert investment["error_item_count"] == 3
    assert investment["detected_error_item_count"] == 1
    issue_item = next(item for item in investment["check_items"] if item["id"] == "issue-1")
    assert issue_item["evidence_locations"][0]["page_number"] == 12


def test_build_review_rule_topics_uses_configured_check_items():
    topics = build_review_rule_topics(
        [],
        configured_check_items=[
            {
                "id": "custom-1",
                "topic_id": "scmc-010",
                "executor_type_id": "custom_executor",
                "review_type": "植物配置专项核验",
                "review_sub_type": "乔灌草配置完整性",
                "target_fields": ["乔木", "灌木", "草种"],
                "regulation_clauses": ["人工配置条款"],
                "review_criteria": "核查植物措施是否形成乔灌草配置闭环。",
                "expected_result": "乔木、灌木、草种配置均有明确证据。",
                "failure_conditions": ["缺少乔木配置", "缺少草种说明"],
            }
        ],
    )

    plant = next(topic for topic in topics if topic["name"] == "植物措施")
    assert plant["check_items"][0]["id"] == "custom-1"
    assert plant["check_items"][0]["review_type"] == "植物配置专项核验"
    assert plant["check_items"][0]["review_logic_types"] == ["custom_executor"]
    assert plant["check_items"][0]["target_fields"] == ["乔木", "灌木", "草种"]
    assert plant["check_items"][0]["review_criteria"] == "核查植物措施是否形成乔灌草配置闭环。"
    assert plant["check_items"][0]["expected_result"] == "乔木、灌木、草种配置均有明确证据。"
    assert plant["check_items"][0]["failure_conditions"] == ["缺少乔木配置", "缺少草种说明"]
    assert plant["check_items"][0]["reasoning_process"]["review_rule"]["criteria"] == "核查植物措施是否形成乔灌草配置闭环。"
    assert plant["check_item_count"] == 15
    assert plant["configured_check_item_count"] == 1
    assert "覆盖15个核验点" in plant["description"]
    assert all("核验点" not in item["review_sub_type"] for item in plant["check_items"])


def test_enabled_configured_item_keeps_rule_candidates_without_active_rule_fallback():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "PLANT-CANDIDATE-001",
                "rule_name": "植物措施配置审查",
                "category": "措施布设类",
                "target_fields": ["植物措施"],
                "evidence_requirement": "需核验植物措施配置。",
            }
        ],
        configured_check_items=[
            {
                "id": "configured-plant-candidate",
                "topic_id": "scmc-010",
                "executor_type_id": "manual_basic",
                "review_type": "人工基础核验",
                "review_sub_type": "已启用植物措施配置审查",
                "enabled": True,
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")

    assert any(rule["rule_id"] == "PLANT-CANDIDATE-001" for rule in plant["rule_candidates"])
    assert not any(
        item["rule_id"] == "PLANT-CANDIDATE-001" and item["ai_or_human_source"] == "rule_set"
        for item in plant["check_items"]
    )
    assert not any(item["ai_or_human_source"] == "planned_checklist" for item in plant["check_items"])


def test_disabled_configured_check_items_remain_visible_in_rule_topics():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "PLANT-DISABLED-FALLBACK",
                "rule_name": "植物措施配置审查",
                "category": "措施布设类",
                "target_fields": ["植物措施"],
                "evidence_requirement": "需核验植物措施配置。",
            }
        ],
        configured_check_items=[
            {
                "id": "disabled-plant-1",
                "topic_id": "scmc-010",
                "executor_type_id": "manual_special",
                "review_type": "人工专项核验",
                "review_sub_type": "停用植物措施配置审查",
                "status": "failed",
                "enabled": False,
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")
    disabled_item = next(item for item in plant["check_items"] if item["id"] == "disabled-plant-1")
    assert disabled_item["enabled"] is False
    assert disabled_item["status"] == "disabled"
    assert disabled_item["ai_or_human_source"] == "configured_checklist"
    assert any(item["rule_id"] == "PLANT-DISABLED-FALLBACK" for item in plant["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in plant["check_items"])
    assert plant["check_status"] == "pending"
    assert plant["configured_check_item_count"] == 1
    assert plant["detected_error_item_count"] == 0


def test_disabled_configured_item_does_not_consume_single_planned_fallback_slot():
    topics = build_review_rule_topics(
        [],
        configured_check_items=[
            {
                "id": "disabled-road-1",
                "topic_id": "scmc-005",
                "executor_type_id": "manual_basic",
                "review_type": "人工基础核验",
                "review_sub_type": "停用施工便道审查项",
                "status": "failed",
                "enabled": False,
            }
        ],
    )

    road = next(topic for topic in topics if topic["id"] == "scmc-005")
    disabled_item = next(item for item in road["check_items"] if item["id"] == "disabled-road-1")

    assert disabled_item["status"] == "disabled"
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in road["check_items"])
    assert road["check_status"] == "pending"
    assert road["configured_check_item_count"] == 1
    assert road["detected_error_item_count"] == 0


def test_configured_check_items_are_prioritized_before_issues_and_same_rule_id_is_preserved():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "PLANT-001",
                "rule_name": "植物措施配置审查",
                "category": "措施布设类",
                "target_fields": ["植物措施"],
                "evidence_requirement": "需核验植物措施配置。",
            }
        ],
        [
            {
                "id": "issue-plant-1",
                "risk_category": "措施布设类",
                "risk_level": "HIGH",
                "source_type": "ai",
                "ai_finding": "植物措施缺少乔灌草配置说明。",
                "ai_reasoning": '{"rule_id":"PLANT-001","rule_name":"植物措施配置审查"}',
                "human_decision": "pending",
            }
        ],
        configured_check_items=[
            {
                "id": "configured-plant-1",
                "topic_id": "scmc-010",
                "rule_id": "PLANT-001",
                "executor_type_id": "manual_special",
                "review_type": "人工专项核验",
                "review_sub_type": "植物措施配置审查",
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")
    assert [item["id"] for item in plant["check_items"][:2]] == ["configured-plant-1", "issue-plant-1"]
    assert [item["rule_id"] for item in plant["check_items"][:2]] == ["PLANT-001", "PLANT-001"]
    assert plant["check_status"] == "failed"
    assert plant["check_item_count"] == 15
    assert plant["configured_check_item_count"] == 1
    assert plant["detected_error_item_count"] == 1


def test_topics_without_config_still_fall_back_to_rules_and_planned_items():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "LAND-001",
                "rule_name": "工程占地统计审查",
                "category": "项目概况类",
                "target_fields": ["占地面积"],
                "evidence_requirement": "需核验工程占地。",
            }
        ],
        configured_check_items=[
            {
                "id": "configured-plant-1",
                "topic_id": "scmc-010",
                "executor_type_id": "manual_special",
                "review_type": "人工专项核验",
                "review_sub_type": "植物措施配置审查",
            }
        ],
    )

    engineering_land = next(topic for topic in topics if topic["id"] == "scmc-003")
    assert engineering_land["check_item_count"] == 14
    assert engineering_land["configured_check_item_count"] == 0
    assert any(item["rule_id"] == "LAND-001" for item in engineering_land["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in engineering_land["check_items"])


def test_rule_set_check_item_ids_stay_unique_when_names_repeat():
    topics = build_review_rule_topics(
        [
            {
                "rule_id": "EARTH-001",
                "rule_name": "土石方总量审查",
                "category": "项目概况类",
                "target_fields": ["土石方总量"],
                "evidence_requirement": "需核验土石方总量。",
            },
            {
                "rule_id": "EARTH-002",
                "rule_name": "土石方总量审查",
                "category": "项目概况类",
                "target_fields": ["挖方", "填方"],
                "evidence_requirement": "需核验挖填方。",
            },
        ]
    )

    earthwork = next(topic for topic in topics if topic["id"] == "scmc-002")
    rule_set_items = [
        item for item in earthwork["check_items"]
        if item["ai_or_human_source"] == "rule_set"
    ]
    rule_set_ids = [item["id"] for item in rule_set_items]

    assert {item["rule_id"] for item in rule_set_items} == {"EARTH-001", "EARTH-002"}
    assert len(rule_set_ids) == len(set(rule_set_ids))


def test_topic_count_fields_keep_planned_configured_reference_and_detected_error_counts_separate():
    topics = build_review_rule_topics(
        [],
        [
            {
                "id": "issue-invest-1",
                "risk_category": "投资估算与效益类",
                "risk_level": "HIGH",
                "source_type": "ai",
                "ai_finding": "总投资不一致。",
                "ai_reasoning": '{"rule_id":"INV-001","rule_name":"项目总投资审查"}',
                "human_decision": "pending",
            },
            {
                "id": "issue-invest-2",
                "risk_category": "投资估算与效益类",
                "risk_level": "MEDIUM",
                "source_type": "ai",
                "ai_finding": "费用构成缺少说明。",
                "ai_reasoning": '{"rule_id":"INV-002","rule_name":"费用构成审查"}',
                "human_decision": "pending",
            },
        ],
        configured_check_items=[
            {
                "id": "configured-invest-1",
                "topic_id": "scmc-001",
                "executor_type_id": "manual_basic",
                "review_type": "人工基础核验",
                "review_sub_type": "项目总投资配置审查",
            }
        ],
    )

    investment = next(topic for topic in topics if topic["id"] == "scmc-001")
    assert investment["check_item_count"] == 11
    assert investment["configured_check_item_count"] == 1
    assert investment["error_item_count"] == 3
    assert investment["reference_error_count"] == 3
    assert investment["detected_error_item_count"] == 2
    assert "覆盖11个核验点" in investment["description"]


def test_execute_rule_precheck_reports_missing_target_fields():
    rule = normalize_review_rule(
        {
            "rule_id": "WSB-GEN-004",
            "rule_name": "工程征占地统计审查",
            "category": "项目概况类",
            "target_fields": ["占地面积", "县级行政区统计"],
            "evidence_requirement": "需提供县级行政区占地统计表。",
        }
    )
    evidence = [
        {
            "document": "项目总占地面积为3.19hm²，其中永久占地1.34hm²。",
            "metadata": {"section": "项目概况"},
        }
    ]

    result = execute_rule_precheck(rule, evidence)

    assert result["execution_status"] == "needs_review"
    assert result["matched_target_fields"] == ["占地面积"]
    assert result["missing_target_fields"] == ["县级行政区统计"]
    assert result["checks"][0]["check_type"] == "target_field_presence"
