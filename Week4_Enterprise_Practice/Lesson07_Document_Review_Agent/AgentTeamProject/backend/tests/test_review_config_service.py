import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.router import api_router
from app.services import review_config_service
from app.services.review_brief_service import meaningful_explicit_fields
from app.services.review_rule_schema import build_review_rule_topics
from app.services.water_review_service import load_rule_set


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "scmc_review_config.json"
    monkeypatch.setattr(review_config_service, "CONFIG_PATH", config_path)
    return config_path


def _write_config(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_default_config_contains_manual_basic_and_no_synthetic_check_items(isolated_config):
    config = review_config_service.load_review_config()

    assert any(item["id"] == "manual_basic" for item in config["executor_types"])
    assert config["check_items"] == []
    assert review_config_service.list_check_item_specs() == []


def test_crud_executor_type_and_check_item_via_api(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)

    executor = client.post(
        "/api/v1/review-config/executor-types",
        json={"id": "custom_ai", "label": "自定义 AI 审查", "description": "专项执行器"},
    )
    assert executor.status_code == 200
    assert executor.json()["id"] == "custom_ai"

    updated_executor = client.patch(
        "/api/v1/review-config/executor-types/custom_ai",
        json={"label": "自定义 AI 复核", "enabled": False},
    )
    assert updated_executor.status_code == 200
    assert updated_executor.json()["label"] == "自定义 AI 复核"
    assert updated_executor.json()["enabled"] is False

    reenabled_executor = client.patch(
        "/api/v1/review-config/executor-types/custom_ai",
        json={"enabled": True},
    )
    assert reenabled_executor.status_code == 200
    assert reenabled_executor.json()["enabled"] is True

    check_item = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "plant-custom",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-RULE-001",
            "executor_type_id": "custom_ai",
            "review_type": "植物措施专项审查",
            "review_sub_type": "乔灌草配置完整性",
            "conclusion": "待核验",
            "evidence_scope": {"sections": ["植物措施"]},
            "target_fields": ["乔木", "灌木"],
            "regulation_clauses": ["条款 A"],
            "enabled": True,
        },
    )
    assert check_item.status_code == 200
    assert check_item.json()["executor_type_id"] == "custom_ai"
    assert check_item.json()["rule_id"] == "PLANT-RULE-001"

    listed = client.get("/api/v1/review-config/check-items", params={"topic_id": "scmc-010"})
    assert listed.status_code == 200
    assert any(item["id"] == "plant-custom" for item in listed.json()["items"])
    assert next(item for item in listed.json()["items"] if item["id"] == "plant-custom")["rule_id"] == "PLANT-RULE-001"

    patched = client.patch("/api/v1/review-config/check-items/plant-custom", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    deleted_check = client.delete("/api/v1/review-config/check-items/plant-custom")
    assert deleted_check.status_code == 200
    assert deleted_check.json()["deleted"] is True

    deleted_executor = client.delete("/api/v1/review-config/executor-types/custom_ai")
    assert deleted_executor.status_code == 200
    assert deleted_executor.json()["deleted"] is True


def test_patch_executor_type_preserves_unsubmitted_fields(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    client.post(
        "/api/v1/review-config/executor-types",
        json={
            "id": "disabled_executor",
            "label": "原始执行器",
            "description": "原始说明",
            "enabled": False,
        },
    )

    response = client.patch("/api/v1/review-config/executor-types/disabled_executor", json={"label": "更新名称"})

    assert response.status_code == 200
    assert response.json()["label"] == "更新名称"
    assert response.json()["description"] == "原始说明"
    assert response.json()["enabled"] is False


def test_patch_check_item_preserves_unsubmitted_fields(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "disabled-check",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "review_type": "植物措施专项审查",
            "review_sub_type": "原始子类型",
            "conclusion": "保留结论",
            "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
            "target_fields": ["乔木", "灌木"],
            "regulation_clauses": ["条款 A"],
            "review_criteria": "核查植物措施是否覆盖乔灌草配置要求。",
            "expected_result": "植物措施配置完整且有表格支撑。",
            "failure_conditions": ["未见乔木配置", "未见灌木配置"],
            "source_rule_snapshot": {"rule_id": "PLANT-RULE-001", "copied": True},
            "enabled": False,
        },
    )

    response = client.patch("/api/v1/review-config/check-items/disabled-check", json={"review_sub_type": "更新子类型"})

    assert response.status_code == 200
    assert response.json()["review_sub_type"] == "更新子类型"
    assert response.json()["enabled"] is False
    assert response.json()["conclusion"] == "保留结论"
    assert response.json()["evidence_scope"] == {"sections": ["植物措施"], "tables": ["植物措施工程量表"]}
    assert response.json()["target_fields"] == ["乔木", "灌木"]
    assert response.json()["regulation_clauses"] == ["条款 A"]
    assert response.json()["review_criteria"] == "核查植物措施是否覆盖乔灌草配置要求。"
    assert response.json()["expected_result"] == "植物措施配置完整且有表格支撑。"
    assert response.json()["failure_conditions"] == ["未见乔木配置", "未见灌木配置"]
    assert response.json()["source_rule_snapshot"] == {"rule_id": "PLANT-RULE-001", "copied": True}


def test_check_item_api_round_trips_evidence_slots_and_formula_checks(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    evidence_slots = [
        {
            "id": "earthwork_volumes",
            "label": "土石方工程量",
            "required": True,
            "queries": ["土石方平衡 挖方 填方 借方 弃方"],
            "expected_terms": ["挖方", "填方", "借方", "弃方"],
            "preferred_sections": ["项目概况", "土石方平衡"],
        }
    ]
    formula_checks = [
        {
            "id": "earthwork_total_balance",
            "label": "土石方总量平衡",
            "expression": "excavation_volume + borrow_volume == fill_volume + spoil_volume",
            "left_fields": ["excavation_volume", "borrow_volume"],
            "right_fields": ["fill_volume", "spoil_volume"],
            "tolerance": {"type": "relative_or_absolute", "relative": 0.01, "absolute": 0.01, "unit": "万m3"},
            "required": True,
        }
    ]

    created = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "earthwork-slots",
            "topic_id": "scmc-002",
            "executor_type_id": "manual_basic",
            "review_type": "土石方专项审查",
            "review_sub_type": "土石方平衡（含表土）完整性",
            "evidence_slots": evidence_slots,
            "formula_checks": formula_checks,
        },
    )

    assert created.status_code == 200
    assert created.json()["evidence_slots"] == evidence_slots
    assert created.json()["formula_checks"] == formula_checks

    listed = client.get("/api/v1/review-config/check-items", params={"topic_id": "scmc-002"})
    item = next(candidate for candidate in listed.json()["items"] if candidate["id"] == "earthwork-slots")
    assert item["evidence_slots"] == evidence_slots
    assert item["formula_checks"] == formula_checks

    patched = client.patch(
        "/api/v1/review-config/check-items/earthwork-slots",
        json={
            "review_sub_type": "土石方平衡与表土单独平衡",
            "evidence_slots": [
                *evidence_slots,
                {
                    "id": "topsoil_balance",
                    "label": "表土单独平衡",
                    "required": True,
                    "queries": ["表土 剥离 保存 回覆 平衡"],
                    "expected_terms": ["表土", "剥离", "回覆"],
                },
            ],
        },
    )

    assert patched.status_code == 200
    assert patched.json()["review_sub_type"] == "土石方平衡与表土单独平衡"
    assert [slot["id"] for slot in patched.json()["evidence_slots"]] == ["earthwork_volumes", "topsoil_balance"]
    assert patched.json()["formula_checks"] == formula_checks

    cleared = client.patch(
        "/api/v1/review-config/check-items/earthwork-slots",
        json={
            "evidence_slots": [],
            "formula_checks": [],
        },
    )

    assert cleared.status_code == 200
    assert cleared.json()["evidence_slots"] == []
    assert cleared.json()["formula_checks"] == []


def test_check_item_defaults_structured_review_fields_to_empty_lists(isolated_config):
    _write_config(
        isolated_config,
        {
            "executor_types": [{"id": "manual_basic", "label": "人工基础核验", "enabled": True}],
            "check_items": [
                {
                    "id": "legacy-no-structured-fields",
                    "topic_id": "scmc-001",
                    "executor_type_id": "manual_basic",
                    "review_type": "人工基础核验",
                    "review_sub_type": "旧配置项",
                }
            ],
        },
    )

    item = review_config_service.list_check_item_specs()[0]

    assert item["evidence_slots"] == []
    assert item["formula_checks"] == []


def test_create_check_item_normalizes_expert_brief(isolated_config):
    expert_brief = {
        "item_name": "土石方平衡与投资口径审查",
        "review_objective": "核查项目总投资、土石方、工程占地是否前后一致。",
        "evidence_instruction": "去项目概况章节、土石方平衡表、附件和相关规范条款找证据。",
        "judgement_basis": "按水土保持方案审查经验，工程数量应与投资估算口径一致。",
        "pass_condition": "项目总投资、挖方、借方和工程占地均有明确来源且相互一致。",
        "issue_condition": "未说明项目总投资；土石方表缺少挖方或借方。工程占地与附件不一致",
        "regulation_text": "《生产建设项目水土保持技术标准》第 4.1.2 条；地方审查口径第 3 条",
    }

    item = review_config_service.create_check_item_spec(
        {
            "id": "brief-normalized",
            "topic_id": "scmc-001",
            "executor_type_id": "manual_basic",
            "expert_brief": expert_brief,
        }
    )

    assert item["review_sub_type"] == "土石方平衡与投资口径审查"
    assert "判断依据：按水土保持方案审查经验" in item["review_criteria"]
    assert "审查目标：核查项目总投资、土石方、工程占地是否前后一致。" in item["review_criteria"]
    assert "证据说明：去项目概况章节、土石方平衡表、附件和相关规范条款找证据。" in item["review_criteria"]
    assert item["expected_result"] == "项目总投资、挖方、借方和工程占地均有明确来源且相互一致。"
    assert item["failure_conditions"] == ["未说明项目总投资", "土石方表缺少挖方或借方", "工程占地与附件不一致"]
    assert item["regulation_clauses"] == ["《生产建设项目水土保持技术标准》第 4.1.2 条", "地方审查口径第 3 条"]
    assert item["evidence_scope"]["instructions"] == "去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"
    assert item["evidence_scope"]["sections"] == ["去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"]
    assert item["evidence_scope"]["chapters"] == ["去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"]
    assert item["evidence_scope"]["tables"] == ["去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"]
    assert item["evidence_scope"]["attachments"] == ["去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"]
    assert item["evidence_scope"]["regulations"] == ["去项目概况章节、土石方平衡表、附件和相关规范条款找证据。"]
    for field in ["项目总投资", "土石方", "工程占地", "挖方", "借方"]:
        assert field in item["target_fields"]
    assert item["source_rule_snapshot"]["expert_brief"] == expert_brief
    assert item["source_rule_snapshot"]["normalized_from_expert_brief"] is True


def test_create_check_item_via_api_derives_expert_brief_defaults(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    expert_brief = {
        "item_name": "植物措施乔灌草核验",
        "review_objective": "核查植物措施中的乔木、灌木配置是否完整。",
        "evidence_instruction": "查看植物措施章节和植物措施工程量表。",
        "judgement_basis": "以植物措施配置和工程量表支撑情况作为判断依据。",
        "pass_condition": "植物措施、乔木、灌木配置均有明确数量和表格支撑。",
        "issue_condition": "未见乔木配置；未见灌木配置；植物措施工程量表缺失",
        "regulation_text": "植物措施审查口径：应核验乔木、灌木等植物措施配置及工程量表支撑。",
    }

    response = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "brief-api-derived",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "expert_brief": expert_brief,
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["review_sub_type"] == "植物措施乔灌草核验"
    for field in ["植物措施", "乔木", "灌木"]:
        assert field in item["target_fields"]
    assert item["evidence_scope"]["instructions"] == "查看植物措施章节和植物措施工程量表。"
    assert item["failure_conditions"] == ["未见乔木配置", "未见灌木配置", "植物措施工程量表缺失"]
    assert item["regulation_clauses"] == [
        "植物措施审查口径：应核验乔木、灌木等植物措施配置及工程量表支撑"
    ]
    assert item["source_rule_snapshot"]["expert_brief"] == expert_brief
    assert item["source_rule_snapshot"]["normalized_from_expert_brief"] is True


def test_create_check_item_via_api_ignores_empty_advanced_fields_for_expert_brief_derivation(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    expert_brief = {
        "item_name": "土石方投资口径核验",
        "review_objective": "核查项目总投资、土石方、工程占地是否一致。",
        "evidence_instruction": "查看项目概况章节、土石方平衡表、附件和规范条款。",
        "judgement_basis": "以投资估算、工程数量和附件口径一致性作为判断依据。",
        "pass_condition": "项目总投资、挖方、借方和工程占地均有明确来源且相互一致。",
        "issue_condition": "未说明项目总投资；土石方表缺少挖方或借方；工程占地与附件不一致",
        "regulation_text": "《生产建设项目水土保持技术标准》第 4.1.2 条；地方审查口径第 3 条",
    }

    response = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "brief-api-empty-advanced",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "expert_brief": expert_brief,
            "evidence_scope": {
                "chapters": [],
                "tables": [],
                "attachments": [],
                "regulations": [],
                "instructions": "",
                "legacy_flag": False,
            },
            "target_fields": [],
            "regulation_clauses": [],
            "review_criteria": "",
            "expected_result": "",
            "failure_conditions": [],
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["expected_result"] == "项目总投资、挖方、借方和工程占地均有明确来源且相互一致。"
    assert item["failure_conditions"] == ["未说明项目总投资", "土石方表缺少挖方或借方", "工程占地与附件不一致"]
    assert item["regulation_clauses"] == ["《生产建设项目水土保持技术标准》第 4.1.2 条", "地方审查口径第 3 条"]
    assert "判断依据：以投资估算、工程数量和附件口径一致性作为判断依据。" in item["review_criteria"]
    assert item["evidence_scope"]["instructions"] == "查看项目概况章节、土石方平衡表、附件和规范条款。"
    for field in ["项目总投资", "土石方", "工程占地", "挖方", "借方"]:
        assert field in item["target_fields"]


def test_meaningful_explicit_fields_treats_false_as_empty_advanced_value():
    fields = meaningful_explicit_fields(
        {
            "expert_brief": {"item_name": "项目总投资"},
            "target_fields": False,
            "evidence_scope": {"chapters": [], "legacy_flag": False},
            "enabled": False,
        }
    )

    assert "expert_brief" in fields
    assert "target_fields" not in fields
    assert "evidence_scope" not in fields


def test_expert_brief_snapshot_drops_legacy_rule_context(isolated_config):
    expert_brief = {
        "item_name": "项目总投资专家简报",
        "review_objective": "核查项目总投资是否一致。",
        "evidence_instruction": "查看项目总投资章节和投资估算表。",
        "judgement_basis": "按专家填写的总投资口径判断。",
        "pass_condition": "金额、单位和来源一致。",
        "issue_condition": "金额不一致",
        "regulation_text": "专家法规口径",
    }

    item = review_config_service.create_check_item_spec(
        {
            "id": "brief-drops-legacy-snapshot",
            "topic_id": "scmc-001",
            "executor_type_id": "manual_basic",
            "expert_brief": expert_brief,
            "source_rule_snapshot": {
                "rule_id": "OLD-RULE",
                "rule_name": "旧模板名称",
                "rule_source": "旧模板法规",
                "evidence_requirement": "旧模板证据要求",
                "ai_or_human_source": "rule_set",
            },
        }
    )

    assert item["source_rule_snapshot"] == {
        "ai_or_human_source": "rule_set",
        "expert_brief": expert_brief,
        "normalized_from_expert_brief": True,
    }


def test_patch_check_item_preserves_expert_brief_snapshot_when_unsubmitted(isolated_config):
    expert_brief = {
        "item_name": "植物措施完整性审查",
        "review_objective": "核查植物措施、临时措施是否有工程量。",
        "evidence_instruction": "查看植物措施章节和措施工程量表。",
        "judgement_basis": "按方案审查口径判断措施配置完整性。",
        "pass_condition": "植物措施和临时措施均有工程量支撑。",
        "issue_condition": "缺少植物措施；缺少临时措施",
    }
    created = review_config_service.create_check_item_spec(
        {
            "id": "brief-patch-preserve",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "expert_brief": expert_brief,
        }
    )

    updated = review_config_service.update_check_item_spec(
        "brief-patch-preserve",
        {"review_type": "人工复核"},
    )

    assert updated["review_type"] == "人工复核"
    assert updated["review_sub_type"] == created["review_sub_type"]
    assert updated["expected_result"] == created["expected_result"]
    assert updated["source_rule_snapshot"]["expert_brief"] == expert_brief
    assert updated["source_rule_snapshot"]["normalized_from_expert_brief"] is True


def test_patch_check_item_rebuilds_expert_brief_derivatives_without_old_brief_text(isolated_config):
    first_brief = {
        "item_name": "旧项目投资审查",
        "review_objective": "核查旧项目总投资是否一致。",
        "evidence_instruction": "查看旧投资估算章节。",
        "judgement_basis": "旧判断依据不得残留。",
        "pass_condition": "旧项目总投资一致。",
        "issue_condition": "旧项目总投资缺失",
    }
    second_brief = {
        "item_name": "新植物措施审查",
        "review_objective": "核查新植物措施是否完整。",
        "evidence_instruction": "查看新植物措施章节和工程量表。",
        "judgement_basis": "新判断依据用于本次审查。",
        "pass_condition": "新植物措施有工程量支撑。",
        "issue_condition": "新植物措施缺失",
    }
    review_config_service.create_check_item_spec(
        {
            "id": "brief-patch-rebuild",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "expert_brief": first_brief,
        }
    )

    updated = review_config_service.update_check_item_spec("brief-patch-rebuild", {"expert_brief": second_brief})

    assert "旧项目总投资" not in updated["review_criteria"]
    assert "旧判断依据" not in updated["review_criteria"]
    assert updated["evidence_scope"]["instructions"] == "查看新植物措施章节和工程量表。"
    assert "旧投资估算章节" not in updated["evidence_scope"]["instructions"]
    assert updated["failure_conditions"] == ["新植物措施缺失"]
    assert "项目总投资" not in updated["target_fields"]
    assert "植物措施" in updated["target_fields"]
    assert updated["source_rule_snapshot"]["expert_brief"] == second_brief
    assert updated["source_rule_snapshot"]["normalized_from_expert_brief"] is True


def test_patch_check_item_expert_brief_respects_explicit_structured_fields(isolated_config):
    initial_brief = {
        "item_name": "初始审查",
        "review_objective": "核查土石方。",
        "evidence_instruction": "查看土石方章节。",
        "judgement_basis": "初始依据。",
        "pass_condition": "土石方一致。",
        "issue_condition": "土石方缺失",
    }
    patched_brief = {
        "item_name": "brief 子类型不应覆盖",
        "review_objective": "核查植物措施。",
        "evidence_instruction": "查看植物措施章节。",
        "judgement_basis": "brief 依据仍可写入 criteria。",
        "pass_condition": "brief 通过条件不应覆盖。",
        "issue_condition": "植物措施缺失",
    }
    review_config_service.create_check_item_spec(
        {
            "id": "brief-explicit-priority",
            "topic_id": "scmc-010",
            "executor_type_id": "manual_basic",
            "expert_brief": initial_brief,
        }
    )

    updated = review_config_service.update_check_item_spec(
        "brief-explicit-priority",
        {
            "expert_brief": patched_brief,
            "expected_result": "专家手动指定通过条件。",
            "review_sub_type": "专家手动子类型",
            "target_fields": ["专家手动字段"],
        },
    )

    assert updated["expected_result"] == "专家手动指定通过条件。"
    assert updated["review_sub_type"] == "专家手动子类型"
    assert updated["target_fields"] == ["专家手动字段"]
    assert updated["source_rule_snapshot"]["expert_brief"] == patched_brief
    assert updated["source_rule_snapshot"]["normalized_from_expert_brief"] is True


def test_save_review_config_writes_readable_json_without_tmp_leftovers(isolated_config):
    review_config_service.save_review_config(
        {
            "version": 1,
            "executor_types": [{"id": "manual_basic", "label": "人工基础核验", "enabled": True}],
            "check_items": [
                {
                    "id": "scmc-001-basic",
                    "topic_id": "scmc-001",
                    "executor_type_id": "manual_basic",
                    "review_sub_type": "项目总投资基础审查",
                }
            ],
        }
    )

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["check_items"][0]["id"] == "scmc-001-basic"
    assert list(isolated_config.parent.glob(f".{isolated_config.name}.*.tmp")) == []


def test_create_check_item_rejects_invalid_topic_or_executor(isolated_config):
    with pytest.raises(ValueError, match="Unknown topic_id"):
        review_config_service.create_check_item_spec(
            {
                "id": "bad-topic",
                "topic_id": "not-a-topic",
                "executor_type_id": "manual_basic",
                "review_sub_type": "非法主题",
            }
        )

    with pytest.raises(ValueError, match="Unknown executor_type_id"):
        review_config_service.create_check_item_spec(
            {
                "id": "bad-executor",
                "topic_id": "scmc-001",
                "executor_type_id": "not-an-executor",
                "review_sub_type": "非法执行器",
            }
        )


def test_update_check_item_rejects_invalid_topic_or_executor(isolated_config):
    review_config_service.create_check_item_spec(
        {
            "id": "valid-item",
            "topic_id": "scmc-001",
            "executor_type_id": "manual_basic",
            "review_sub_type": "合法审查项",
        }
    )

    with pytest.raises(ValueError, match="Unknown topic_id"):
        review_config_service.update_check_item_spec("valid-item", {"topic_id": "not-a-topic"})

    with pytest.raises(ValueError, match="Unknown executor_type_id"):
        review_config_service.update_check_item_spec("valid-item", {"executor_type_id": "not-an-executor"})


def test_enabled_check_item_rejects_disabled_executor_but_disabled_item_can_keep_it(isolated_config):
    review_config_service.create_executor_type({"id": "paused_executor", "label": "暂停执行器", "enabled": False})

    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)

    enabled_create = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "enabled-with-disabled-executor",
            "topic_id": "scmc-001",
            "executor_type_id": "paused_executor",
            "review_sub_type": "启用审查项",
            "enabled": True,
        },
    )
    assert enabled_create.status_code == 400

    disabled_create = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "disabled-with-disabled-executor",
            "topic_id": "scmc-001",
            "executor_type_id": "paused_executor",
            "review_sub_type": "停用审查项",
            "enabled": False,
        },
    )
    assert disabled_create.status_code == 200
    assert disabled_create.json()["executor_type_id"] == "paused_executor"
    assert disabled_create.json()["enabled"] is False

    enable_patch = client.patch(
        "/api/v1/review-config/check-items/disabled-with-disabled-executor",
        json={"enabled": True},
    )
    assert enable_patch.status_code == 400


def test_disable_executor_rejects_enabled_references_but_allows_disabled_references(isolated_config):
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)

    client.post("/api/v1/review-config/executor-types", json={"id": "referenced_executor", "label": "被引用执行器"})
    client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "enabled-reference",
            "topic_id": "scmc-001",
            "executor_type_id": "referenced_executor",
            "review_sub_type": "启用引用项",
            "enabled": True,
        },
    )

    blocked = client.patch("/api/v1/review-config/executor-types/referenced_executor", json={"enabled": False})

    assert blocked.status_code == 400
    assert "enabled check item" in blocked.json()["detail"]["message"]

    disabled_item = client.patch("/api/v1/review-config/check-items/enabled-reference", json={"enabled": False})
    assert disabled_item.status_code == 200

    allowed = client.patch("/api/v1/review-config/executor-types/referenced_executor", json={"enabled": False})

    assert allowed.status_code == 200
    assert allowed.json()["enabled"] is False


def test_string_false_and_zero_are_parsed_as_false(isolated_config):
    _write_config(
        isolated_config,
        {
            "version": 1,
            "executor_types": [{"id": "manual_basic", "label": "人工基础核验", "enabled": "false"}],
            "check_items": [
                {
                    "id": "string-bool-item",
                    "topic_id": "scmc-001",
                    "executor_type_id": "manual_basic",
                    "review_sub_type": "字符串布尔值审查项",
                    "enabled": "0",
                }
            ],
        },
    )

    config = review_config_service.load_review_config()

    assert config["executor_types"][0]["enabled"] is False
    assert config["check_items"][0]["enabled"] is False


def test_delete_executor_repoints_existing_check_items_to_manual_basic(isolated_config):
    review_config_service.create_executor_type({"id": "temporary", "label": "临时执行器"})
    review_config_service.create_check_item_spec(
        {
            "id": "temporary-item",
            "topic_id": "scmc-001",
            "executor_type_id": "temporary",
            "review_type": "临时审查",
            "review_sub_type": "临时核验",
        }
    )

    review_config_service.delete_executor_type("temporary")

    item = next(item for item in review_config_service.list_check_item_specs() if item["id"] == "temporary-item")
    assert item["executor_type_id"] == "manual_basic"
    assert item["review_type"] == "人工基础核验"


def test_disabled_check_items_survive_normalization(isolated_config):
    review_config_service.create_check_item_spec(
        {
            "id": "disabled-item",
            "topic_id": "scmc-001",
            "review_sub_type": "可停用审查项",
            "enabled": False,
        }
    )

    item = next(item for item in review_config_service.list_check_item_specs() if item["id"] == "disabled-item")
    assert item["enabled"] is False


def test_empty_executor_types_falls_back_to_manual_basic(isolated_config):
    _write_config(
        isolated_config,
        {
            "version": 1,
            "executor_types": [],
            "check_items": [{"id": "orphan", "topic_id": "scmc-001", "executor_type_id": "missing"}],
        },
    )

    config = review_config_service.load_review_config()

    assert config["executor_types"][0]["id"] == "manual_basic"
    assert config["check_items"][0]["executor_type_id"] == "manual_basic"


def test_missing_check_items_returns_empty_and_rule_topics_can_fallback(isolated_config):
    _write_config(isolated_config, {"version": 1})

    config = review_config_service.load_review_config()
    specs = review_config_service.list_check_item_specs()

    assert config["check_items"] == []
    assert specs == []

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
        configured_check_items=specs,
    )
    engineering_land = next(topic for topic in topics if topic["id"] == "scmc-003")

    assert engineering_land["configured_check_item_count"] == 0
    assert any(item["rule_id"] == "LAND-001" for item in engineering_land["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in engineering_land["check_items"])


def test_empty_seed_config_has_no_active_check_items_and_allows_fallback(isolated_config):
    _write_config(
        isolated_config,
        {
            "version": 1,
            "executor_types": [
                {
                    "id": "manual_basic",
                    "label": "人工基础核验",
                    "description": "基础审查执行类型：定位证据、记录结论，由人工或 LLM 辅助判断。",
                    "enabled": True,
                }
            ],
            "check_items": [],
        },
    )
    specs = review_config_service.list_check_item_specs()

    assert specs == []

    topics = build_review_rule_topics(load_rule_set(), [], configured_check_items=specs)

    assert len(topics) == 20
    assert all(topic["configured_check_item_count"] == 0 for topic in topics)
    assert any(
        item["ai_or_human_source"] == "rule_set"
        for topic in topics
        for item in topic["check_items"]
    )
    assert any(
        item["ai_or_human_source"] == "planned_checklist"
        for topic in topics
        for item in topic["check_items"]
    )


def test_duplicate_ids_are_rejected(isolated_config):
    _write_config(
        isolated_config,
        {
            "version": 1,
            "executor_types": [
                {"id": "manual_basic", "label": "A"},
                {"id": "manual_basic", "label": "B"},
            ],
            "check_items": [],
        },
    )

    with pytest.raises(ValueError, match="Duplicate executor type id"):
        review_config_service.load_review_config()
