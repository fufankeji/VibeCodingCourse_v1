import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.config import settings
from app.database import Base, get_db
from app.models.contract import Contract
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.services import rag_service, retrieval_debug_service, review_agent_service, review_config_service, water_review_service
from app.services.review_rule_schema import build_review_rule_topics


TASK5_RULE = {
    "rule_id": "PLANT-TASK5-001",
    "rule_name": "植物措施配置审查",
    "category": "措施布设类",
    "target_fields": ["植物措施", "乔木", "灌木"],
    "evidence_requirement": "需核验植物措施章节及植物措施工程量表。",
    "rule_source": "水土保持方案审查要点",
}


def _write_review_artifacts(artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "review_chunks.json").write_text(
        json.dumps(
            [
                {
                    "chunk_id": "rag-plant-001",
                    "text": "第5章 植物措施：主体工程区设置乔木120株、灌木800株，植物措施工程量表列明草籽撒播0.42hm2。",
                    "section": "5 植物措施",
                    "page_range": [12, 12],
                    "bbox_list": [
                        {"block_id": "p12-b03", "page": 12, "bbox": [86.0, 320.0, 506.0, 338.0]},
                        {"block_id": "p12-b04", "page": 12, "bbox": [86.0, 342.0, 506.0, 380.0]},
                    ],
                    "table_refs": ["植物措施工程量表"],
                    "metadata": {"block_type": "table"},
                    "char_start": 0,
                    "char_end": 54,
                },
                {
                    "chunk_id": "rag-temp-noise-001",
                    "text": "第6章 临时措施：临时堆土区排水沟需要补充断面尺寸。",
                    "section": "6 临时措施",
                    "page_range": [18, 18],
                    "bbox_list": [],
                    "table_refs": [],
                    "metadata": {"block_type": "text"},
                    "char_start": 55,
                    "char_end": 90,
                },
                {
                    "chunk_id": "rag-project-body-001",
                    "text": (
                        "1.1 项目概况 建设内容：项目建设内容包括1-5#共5栋高层住宅楼、"
                        "1栋2层配套用房、地下2层车库及设备用房。建设规模：总建筑面积81700.84平方米，"
                        "其中地上建筑面积53250.00平方米，地下建筑面积28450.84平方米。"
                    ),
                    "section": "1.1 项目概况",
                    "page_range": [10, 11],
                    "bbox_list": [{"block_id": "p10-b01", "page": 10, "bbox": [86.0, 120.0, 506.0, 220.0]}],
                    "table_refs": [],
                    "metadata": {"block_type": "text"},
                    "char_start": 91,
                    "char_end": 180,
                },
                {
                    "chunk_id": "rag-project-approval-001",
                    "text": (
                        "国家新闻出版广电总局关于朝阳区百子湾职工住宅项目初步设计的批复。"
                        "核定项目建筑面积为80836.65平方米，其中地上建筑面积53250平方米，"
                        "地下建筑面积27586.65平方米。"
                    ),
                    "section": "附件4 初步设计批复",
                    "page_range": [136, 137],
                    "bbox_list": [{"block_id": "p136-b02", "page": 136, "bbox": [80.0, 140.0, 510.0, 260.0]}],
                    "table_refs": [],
                    "metadata": {"block_type": "text"},
                    "char_start": 181,
                    "char_end": 260,
                },
                {
                    "chunk_id": "rag-earthwork-001",
                    "text": (
                        "1.3.2 土石方平衡：本项目挖方10.00万m3，填方8.00万m3，"
                        "借方2.00万m3，弃方4.00万m3，借方来源为合法商品土，弃方外运综合利用。"
                    ),
                    "section": "1.3.2 土石方平衡",
                    "page_range": [22, 22],
                    "bbox_list": [{"block_id": "p22-b01", "page": 22, "bbox": [86.0, 220.0, 506.0, 300.0]}],
                    "table_refs": ["土石方平衡表"],
                    "metadata": {"block_type": "table"},
                    "char_start": 261,
                    "char_end": 360,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "langextract_facts.json").write_text(
        json.dumps(
            [
                {
                    "fact_id": "fact-plant-001",
                    "field_name": "乔木",
                    "value": "120株",
                    "normalized_value": 120,
                    "unit": "株",
                    "section": "5 植物措施",
                    "chunk_id": "rag-plant-001",
                    "page_range": [12, 12],
                    "source_text": "主体工程区设置乔木120株、灌木800株",
                    "confidence": 91,
                },
                {
                    "fact_id": "fact-earthwork-excavation",
                    "field_name": "excavation_volume",
                    "value": "10.00万m3",
                    "normalized_value": "10.00",
                    "unit": "万m3",
                    "section": "1.3.2 土石方平衡",
                    "chunk_id": "rag-earthwork-001",
                    "page_range": [22, 22],
                    "source_text": "挖方10.00万m3",
                    "confidence": 91,
                },
                {
                    "fact_id": "fact-earthwork-fill",
                    "field_name": "fill_volume",
                    "value": "8.00万m3",
                    "normalized_value": "8.00",
                    "unit": "万m3",
                    "section": "1.3.2 土石方平衡",
                    "chunk_id": "rag-earthwork-001",
                    "page_range": [22, 22],
                    "source_text": "填方8.00万m3",
                    "confidence": 91,
                },
                {
                    "fact_id": "fact-earthwork-borrow",
                    "field_name": "borrow_volume",
                    "value": "2.00万m3",
                    "normalized_value": "2.00",
                    "unit": "万m3",
                    "section": "1.3.2 土石方平衡",
                    "chunk_id": "rag-earthwork-001",
                    "page_range": [22, 22],
                    "source_text": "借方2.00万m3",
                    "confidence": 91,
                },
                {
                    "fact_id": "fact-earthwork-spoil",
                    "field_name": "spoil_volume",
                    "value": "4.00万m3",
                    "normalized_value": "4.00",
                    "unit": "万m3",
                    "section": "1.3.2 土石方平衡",
                    "chunk_id": "rag-earthwork-001",
                    "page_range": [22, 22],
                    "source_text": "弃方4.00万m3",
                    "confidence": 91,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "cross_chapter_findings.json").write_text(
        json.dumps(
            [
                {
                    "finding_id": "finding-plant-001",
                    "finding_type": "table_text_consistency",
                    "field_name": "乔木",
                    "description": "植物措施章节与植物措施工程量表均出现乔木数量。",
                    "risk_level": "LOW",
                    "actual_value": "乔木120株",
                    "expected_value": "章节和表格应互相支撑",
                    "fact_ids": ["fact-plant-001"],
                    "source_pages": [12],
                    "evidence_text": "主体工程区设置乔木120株、灌木800株",
                    "confidence": 89,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class FakeEmbedder:
    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        vectors = []
        for text in texts:
            vectors.append(
                [
                    float(text.count("植物") + text.count("乔木") + text.count("灌木") + 1),
                    float(text.count("临时") + text.count("排水沟") + 1),
                    float((len(text) % 7) + 1),
                ]
            )
        return vectors


class FakeReranker:
    def rerank(self, query: str, matches: list[dict], top_n: int) -> list[dict]:
        ranked = []
        for index, match in enumerate(matches[:top_n], start=1):
            item = dict(match)
            item["rerank_rank"] = index
            item["rerank_score"] = 1.0 / index
            ranked.append(item)
        return ranked


class FakeLLM:
    def invoke(self, messages):
        class Response:
            content = json.dumps(
                {
                    "status": "pass",
                    "summary": "已基于召回证据核验植物措施配置，乔木和灌木数量均有表格支撑。",
                    "actual_value": "乔木120株，灌木800株",
                    "expected_value": "植物措施配置完整且有表格支撑。",
                    "fix_suggestion": "无需修改，保存前由专家确认口径。",
                    "confidence": 86,
                    "next_action": "可保存为审查项规则。",
                },
                ensure_ascii=False,
            )

        return Response()


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "scmc_review_config.json"
    monkeypatch.setattr(review_config_service, "CONFIG_PATH", config_path)
    return config_path


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    source_file = tmp_path / "contracts" / "task5-contract" / "北京航空航天大学沙河校区图书馆项目-mineru.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("dummy pdf payload", encoding="utf-8")
    artifact_dir = source_file.parent / "water_review"
    _write_review_artifacts(artifact_dir)

    monkeypatch.setattr(settings, "storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "siliconflow_api_key", "test-siliconflow-key")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-deepseek-key")
    monkeypatch.setattr(settings, "review_llm_api_key", "test-review-llm-key")
    monkeypatch.setattr(settings, "review_llm_model", "fake-review-llm")
    monkeypatch.setattr(settings, "siliconflow_embedding_dimensions", 3)
    monkeypatch.setattr(settings, "rag_top_k", 4)
    monkeypatch.setattr(settings, "rag_rerank_top_n", 3)
    monkeypatch.setattr(review_agent_service, "SiliconFlowEmbeddingProvider", FakeEmbedder)
    monkeypatch.setattr(rag_service, "SiliconFlowEmbeddingProvider", FakeEmbedder)
    monkeypatch.setattr(rag_service, "SiliconFlowRerankerProvider", lambda: FakeReranker())
    monkeypatch.setattr(review_agent_service, "get_llm", lambda: FakeLLM())

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        db.add(
            Contract(
                id="task5-contract",
                title="北京航空航天大学沙河校区图书馆项目-mineru",
                original_filename=source_file.name,
                file_type="pdf",
                contract_status="completed",
                file_path=str(source_file),
            )
        )
        db.add(ReviewSession(id="task5-session", contract_id="task5-contract", state="hitl_high_risk"))
        db.add(
            ReviewItem(
                id="task5-issue-plant",
                session_id="task5-session",
                clause_text="植物措施章节缺少乔灌草配置说明。",
                page_number=3,
                paragraph_index=2,
                highlight_anchor="chunk-task5-plant",
                risk_level="HIGH",
                confidence_score=88,
                source_type="ai",
                risk_category="措施布设类",
                ai_finding="植物措施缺少乔灌草配置说明。",
                ai_reasoning=json.dumps(
                    {
                        "rule_id": "PLANT-TASK5-001",
                        "rule_name": "植物措施配置审查",
                        "rule_source": "水土保持方案审查要点",
                        "structured_facts": [{"field": "植物措施", "value": "缺少乔灌草配置说明"}],
                        "cross_chapter_findings": [{"field": "植物措施", "finding": "章节与工程量表需要交叉核验"}],
                        "langextract_grounding": {
                            "scenario": "plant_measure_review",
                            "source_span": "植物措施章节缺少乔灌草配置说明",
                        },
                    },
                    ensure_ascii=False,
                ),
                human_decision="pending",
            )
        )
        db.add(
            ReviewItem(
                id="task5-issue-noise",
                session_id="task5-session",
                clause_text="临时堆土场排水沟设置说明不完整。",
                page_number=8,
                paragraph_index=1,
                highlight_anchor="chunk-task5-noise",
                risk_level="MEDIUM",
                confidence_score=71,
                source_type="ai",
                risk_category="临时措施类",
                ai_finding="排水沟设置说明不足。",
                ai_reasoning=json.dumps(
                    {
                        "rule_id": "TEMP-DRAIN-001",
                        "structured_facts": [{"field": "排水沟", "value": "说明不足"}],
                        "cross_chapter_findings": [{"field": "排水沟", "finding": "临时措施章节内部口径不一致"}],
                        "langextract_grounding": {"scenario": "temporary_drainage_review"},
                    },
                    ensure_ascii=False,
                ),
                human_decision="pending",
            )
        )
        db.add(
            ReviewItem(
                id="task5-issue-criteria-only",
                session_id="task5-session",
                clause_text="专项比选依据完整性需要专家复核，未见支撑材料。",
                page_number=9,
                paragraph_index=3,
                highlight_anchor="chunk-task5-criteria",
                risk_level="MEDIUM",
                confidence_score=73,
                source_type="ai",
                risk_category="专家经验类",
                ai_finding="专项比选依据完整性需要补充支撑材料。",
                ai_reasoning=json.dumps(
                    {
                        "rule_id": "EXPERT-CRITERIA-001",
                        "structured_facts": [{"field": "专项比选依据", "value": "未见支撑材料"}],
                        "cross_chapter_findings": [{"field": "专项比选依据", "finding": "正文与附件缺少对应支撑"}],
                        "langextract_grounding": {"scenario": "expert_criteria_review"},
                    },
                    ensure_ascii=False,
                ),
                human_decision="pending",
            )
        )
        db.add(
            ReviewItem(
                id="task5-issue-generic-noise",
                session_id="task5-session",
                clause_text="未见完整配置说明，需要专家复核支撑材料，章节表格审查依据待补充。",
                page_number=10,
                paragraph_index=4,
                highlight_anchor="chunk-task5-generic-noise",
                risk_level="LOW",
                confidence_score=62,
                source_type="ai",
                risk_category="通用审查类",
                ai_finding="配置说明不完整，材料需要复核。",
                ai_reasoning=json.dumps(
                    {
                        "rule_id": "GENERIC-NOISE-001",
                        "structured_facts": [{"field": "通用说明", "value": "泛词噪声"}],
                    },
                    ensure_ascii=False,
                ),
                human_decision="pending",
            )
        )
        db.commit()

    monkeypatch.setattr(water_review_service, "load_rule_set", lambda: [TASK5_RULE])

    app = FastAPI()
    app.state.artifact_dir = artifact_dir
    app.state.TestingSessionLocal = TestingSessionLocal
    app.include_router(api_router)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _plant_topic(client: TestClient) -> dict:
    response = client.get("/api/v1/sessions/task5-session/rule-topics")
    assert response.status_code == 200
    topics = response.json()["topics"]
    assert len(topics) == 20
    return next(topic for topic in topics if topic["id"] == "scmc-010")


def test_review_config_api_drives_rule_topics_lifecycle(isolated_config, client: TestClient):
    baseline = _plant_topic(client)
    assert baseline["configured_check_item_count"] == 0
    assert any(item["ai_or_human_source"] == "rule_set" for item in baseline["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in baseline["check_items"])

    executor_response = client.post(
        "/api/v1/review-config/executor-types",
        json={"id": "task5_custom_executor", "label": "Task 5 自定义执行器"},
    )
    assert executor_response.status_code == 200

    create_response = client.post(
        "/api/v1/review-config/check-items",
        json={
            "id": "task5-plant-config",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-TASK5-001",
            "executor_type_id": "task5_custom_executor",
            "review_type": "植物措施专项核验",
            "review_sub_type": "乔灌草配置完整性",
            "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
            "target_fields": ["乔木", "灌木", "草种"],
            "regulation_clauses": ["水土保持方案审查要点-植物措施"],
            "enabled": True,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["executor_type_id"] == "task5_custom_executor"
    assert created["rule_id"] == "PLANT-TASK5-001"
    assert created["evidence_scope"] == {"sections": ["植物措施"], "tables": ["植物措施工程量表"]}
    assert created["target_fields"] == ["乔木", "灌木", "草种"]
    assert created["regulation_clauses"] == ["水土保持方案审查要点-植物措施"]
    assert created["enabled"] is True

    active = _plant_topic(client)
    assert active["configured_check_item_count"] == baseline["configured_check_item_count"] + 1
    assert [item["id"] for item in active["check_items"][:2]] == ["task5-plant-config", "task5-issue-plant"]
    assert any(rule["rule_id"] == "PLANT-TASK5-001" for rule in active["rule_candidates"])
    assert not any(
        item["rule_id"] == "PLANT-TASK5-001" and item["ai_or_human_source"] == "rule_set"
        for item in active["check_items"]
    )
    active_item = active["check_items"][0]
    assert active_item["status"] == "pending"
    assert active_item["ai_or_human_source"] == "configured_checklist"
    precheck = active_item["reasoning_process"]["executor_precheck"]
    assert precheck["executor_type_id"] == "task5_custom_executor"
    assert precheck["handler_id"] == "manual_basic"
    assert precheck["execution_status"] == "pending"
    assert precheck["checks"]

    patch_response = client.patch("/api/v1/review-config/check-items/task5-plant-config", json={"enabled": False})
    assert patch_response.status_code == 200
    assert patch_response.json()["enabled"] is False

    disabled = _plant_topic(client)
    disabled_item = next(item for item in disabled["check_items"] if item["id"] == "task5-plant-config")
    disabled_precheck = disabled_item["reasoning_process"]["executor_precheck"]
    assert disabled_item["status"] == "disabled"
    assert disabled_precheck["execution_status"] == "disabled"
    assert disabled_precheck["checks"][0]["type"] == "executor_disabled"
    assert any(item["ai_or_human_source"] == "rule_set" for item in disabled["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in disabled["check_items"])

    delete_response = client.delete("/api/v1/review-config/check-items/task5-plant-config")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    deleted = _plant_topic(client)
    assert deleted["configured_check_item_count"] == 0
    assert all(item["id"] != "task5-plant-config" for item in deleted["check_items"])
    assert any(item["ai_or_human_source"] == "rule_set" for item in deleted["check_items"])
    assert any(item["ai_or_human_source"] == "planned_checklist" for item in deleted["check_items"])


def test_preview_check_item_uses_rag_agent_without_saving_config(isolated_config, client: TestClient):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-TASK5-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "review_criteria": "核验植物措施章节是否说明乔木、灌木配置。",
            "expected_result": "植物措施配置完整且有表格支撑。",
            "failure_conditions": ["未见乔木配置", "未见灌木配置"],
            "regulation_clauses": ["水土保持方案审查要点-植物措施"],
            "evidence_slots": [
                {
                    "id": "plant_measure_text",
                    "label": "植物措施文字和表格",
                    "required": True,
                    "queries": ["植物措施 乔木 灌木 工程量表"],
                    "expected_terms": ["乔木", "灌木"],
                    "preferred_sections": ["植物措施"],
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    bundle = data["evidence_bundle"]
    assert data["check_item"]["id"] == "draft-preview"
    assert bundle["source"] == "rag_agent"
    assert bundle["retrieval_matches"]
    first_match = bundle["retrieval_matches"][0]
    assert first_match["chunk_id"] == "rag-plant-001"
    assert first_match["primary_page"] == 12
    assert first_match["page_range"] == [12, 12]
    assert first_match["chunk_index"] == 0
    assert first_match["bbox_count"] == 2
    assert first_match["block_ids"] == ["p12-b03", "p12-b04"]
    assert first_match["anchors"] == [
        {
            "page": 12,
            "block_id": "p12-b03",
            "bbox": [86.0, 320.0, 506.0, 338.0],
            "coordinate_mode": "page_coordinate",
            "page_width": None,
            "page_height": None,
        },
        {
            "page": 12,
            "block_id": "p12-b04",
            "bbox": [86.0, 342.0, 506.0, 380.0],
            "coordinate_mode": "page_coordinate",
            "page_width": None,
            "page_height": None,
        },
    ]
    assert bundle["evidence_locations"][0]["anchors"] == first_match["anchors"]
    assert "乔木120株" in first_match["text"]
    assert "植物措施" in bundle["matched_target_fields"]
    slot_package = bundle["evidence_slot_package"]
    assert slot_package["source"] == "evidence_slots"
    assert slot_package["slot_count"] == 1
    assert slot_package["missing_required_slot_ids"] == []
    assert slot_package["slots"][0]["slot_id"] == "plant_measure_text"
    assert slot_package["slots"][0]["status"] == "matched"
    assert slot_package["slots"][0]["matched_expected_terms"] == ["乔木", "灌木"]
    assert slot_package["slots"][0]["matches"][0]["chunk_id"] == "rag-plant-001"
    assert "bm25" in slot_package["slots"][0]["matches"][0]["retrieval_sources"]
    assert slot_package["slots"][0]["queries"][0]["query"] == "植物措施 乔木 灌木 工程量表"
    assert bundle["structured_facts"][0]["fact_id"] == "fact-plant-001"
    assert bundle["cross_reference_findings"][0]["finding_id"] == "finding-plant-001"
    assert bundle["regulation_context"][0]["text"] == "水土保持方案审查要点-植物措施"
    assert data["precheck_result"]["executor_type_id"] == "evidence_presence"
    assert data["review_conclusion"]["status"] == "pass"
    assert data["review_conclusion"]["actual_value"] == "乔木120株，灌木800株"
    assert data["review_conclusion"]["expected_value"] == "植物措施配置完整且有表格支撑。"
    assert data["agent_trace"]["retrieval_mode"] == "vector_bm25_neighbor_rerank"
    assert data["agent_trace"]["persisted"] is False
    assert data["agent_trace"]["facts_available"] is True
    assert data["suggested_rule_improvements"]
    assert not isolated_config.exists()
    assert review_config_service.list_check_item_specs() == []


def test_preview_evidence_slot_retrieval_limits_queries_and_marks_unconfigured_slots(
    isolated_config,
    client: TestClient,
):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-SLOT-LIMIT-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "植物措施槽位召回",
            "evidence_scope": {"sections": ["植物措施"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "evidence_slots": [
                {
                    "id": "too_many_queries",
                    "label": "多 query 截断",
                    "queries": [
                        "植物措施 乔木",
                        "植物措施 灌木",
                        "植物措施 草籽",
                        "植物措施 第四条不应执行",
                    ],
                    "expected_terms": ["乔木", "灌木", "不存在的植物措施术语"],
                },
                {
                    "id": "missing_queries",
                    "label": "缺少 queries 的槽位",
                    "required": True,
                    "expected_terms": ["乔木"],
                },
                *[
                    {
                        "id": f"overflow_{index}",
                        "label": f"溢出槽位 {index}",
                        "queries": ["植物措施"],
                        "required": index == 8,
                    }
                    for index in range(9)
                ],
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    package = response.json()["evidence_bundle"]["evidence_slot_package"]
    assert package["slot_count"] == 8
    assert package["slot_limit"] == 8
    assert package["truncated"] is True
    assert package["required_slot_count"] == 2
    assert package["matched_required_slot_count"] == 0

    too_many_queries = next(slot for slot in package["slots"] if slot["slot_id"] == "too_many_queries")
    assert too_many_queries["query_count"] == 3
    assert too_many_queries["query_limit"] == 3
    assert too_many_queries["truncated_queries"] is True
    assert too_many_queries["status"] == "missing"
    assert too_many_queries["missing_expected_terms"] == ["不存在的植物措施术语"]

    missing_queries = next(slot for slot in package["slots"] if slot["slot_id"] == "missing_queries")
    assert missing_queries["status"] == "not_configured"
    assert missing_queries["queries"] == []
    assert missing_queries["matches"] == []
    assert package["truncated_required_slot_ids"] == ["overflow_8"]
    assert package["missing_required_slot_ids"] == ["missing_queries", "overflow_8"]
    assert response.json()["evidence_bundle"]["retrieval_matches"][0]["chunk_id"] == "rag-plant-001"
    assert not isolated_config.exists()


def test_preview_evidence_slot_package_separates_prompt_and_trace_matches(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        return {
            "query": query,
            "retrieval_mode": "fake",
            "matches": [
                {
                    "chunk_id": f"slot-match-{index}",
                    "document": f"植物措施 乔木 灌木 第 {index} 条证据",
                    "metadata": {"page_start": index, "page_end": index, "section": "植物措施"},
                    "score": 1.0 / index,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": index},
                }
                for index in range(1, 6)
            ],
        }

    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-SLOT-PROMPT-TRACE-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "槽位 prompt 与 trace 分离",
            "target_fields": ["植物措施"],
            "evidence_slots": [
                {
                    "id": "plant_prompt_trace",
                    "label": "植物措施 prompt evidence",
                    "required": True,
                    "queries": ["植物措施 乔木 灌木"],
                    "expected_terms": ["乔木", "灌木"],
                    "min_matches": 2,
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    slot = response.json()["evidence_bundle"]["evidence_slot_package"]["slots"][0]
    assert slot["status"] == "matched"
    assert slot["min_matches"] == 2
    assert slot["match_count"] == 5
    assert [match["chunk_id"] for match in slot["prompt_matches"]] == [
        "slot-match-1",
        "slot-match-2",
        "slot-match-3",
    ]
    assert [match["chunk_id"] for match in slot["trace_matches"]] == [
        "slot-match-4",
        "slot-match-5",
    ]
    assert slot["prompt_match_limit"] == 3
    assert response.json()["evidence_bundle"]["evidence_slot_package"]["missing_required_slot_ids"] == []
    assert not isolated_config.exists()


def test_preview_llm_prompt_receives_only_prompt_slot_matches(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_prompt: dict = {}

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        return {
            "query": query,
            "retrieval_mode": "fake",
            "matches": [
                {
                    "chunk_id": f"slot-prompt-{index}",
                    "document": f"植物措施 乔木 灌木 第 {index} 条证据",
                    "metadata": {"page_start": index, "page_end": index, "section": "植物措施"},
                    "score": 1.0 / index,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": index},
                }
                for index in range(1, 6)
            ],
        }

    class CapturingLLM:
        def invoke(self, messages):
            captured_prompt.update(json.loads(messages[-1].content))

            class Response:
                content = json.dumps(
                    {
                        "status": "pass",
                        "summary": "已基于槽位证据判断。",
                        "actual_value": "已见乔木和灌木证据。",
                        "expected_value": "植物措施配置完整。",
                        "fix_suggestion": "",
                        "confidence": 80,
                        "next_action": "专家复核。",
                    },
                    ensure_ascii=False,
                )

            return Response()

    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)
    monkeypatch.setattr(review_agent_service, "get_llm", lambda: CapturingLLM())

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-SLOT-PROMPT-BOUND-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "槽位 prompt 证据上限",
            "target_fields": ["植物措施"],
            "evidence_slots": [
                {
                    "id": "plant_prompt_bound",
                    "required": True,
                    "queries": ["植物措施 乔木 灌木"],
                    "expected_terms": ["乔木", "灌木"],
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    api_slot = response.json()["evidence_bundle"]["evidence_slot_package"]["slots"][0]
    prompt_slot = captured_prompt["evidence_slot_package"]["slots"][0]
    assert len(api_slot["matches"]) == 5
    assert [match["chunk_id"] for match in api_slot["trace_matches"]] == ["slot-prompt-4", "slot-prompt-5"]
    assert [match["chunk_id"] for match in prompt_slot["matches"]] == [
        "slot-prompt-1",
        "slot-prompt-2",
        "slot-prompt-3",
    ]
    assert "trace_matches" not in prompt_slot
    assert not isolated_config.exists()


def test_preview_required_evidence_slot_respects_min_matches(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_called():
        raise AssertionError("LLM should not run when required slot has fewer matches than min_matches")

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        return {
            "query": query,
            "retrieval_mode": "fake",
            "matches": [
                {
                    "chunk_id": "single-slot-match",
                    "document": "植物措施 乔木 灌木 只有一条证据",
                    "metadata": {"page_start": 1, "page_end": 1, "section": "植物措施"},
                    "score": 1.0,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": 1},
                }
            ],
        }

    monkeypatch.setattr(review_agent_service, "get_llm", fail_if_called)
    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-SLOT-MIN-MATCHES-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "槽位最小命中数",
            "target_fields": ["植物措施"],
            "evidence_slots": [
                {
                    "id": "plant_min_matches",
                    "required": True,
                    "queries": ["植物措施 乔木 灌木"],
                    "expected_terms": ["乔木", "灌木"],
                    "min_matches": 2,
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    slot = data["evidence_bundle"]["evidence_slot_package"]["slots"][0]
    assert slot["status"] == "missing"
    assert slot["min_matches"] == 2
    assert slot["match_count"] == 1
    assert data["evidence_bundle"]["evidence_slot_package"]["missing_required_slot_ids"] == ["plant_min_matches"]
    assert data["review_conclusion"]["status"] == "needs_evidence"
    assert data["agent_trace"]["llm_skipped"] is True
    assert not isolated_config.exists()


def test_preview_missing_required_evidence_slot_blocks_llm_judgment(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_called():
        raise AssertionError("LLM should not be called when required evidence slots are missing")

    monkeypatch.setattr(review_agent_service, "get_llm", fail_if_called)

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-MISSING-SLOT-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "植物措施缺证据阻断",
            "evidence_scope": {"sections": ["植物措施"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "evidence_slots": [
                {
                    "id": "missing_required_slot",
                    "label": "必填但缺失的槽位",
                    "required": True,
                    "queries": ["植物措施 乔木"],
                    "expected_terms": ["不存在的必填证据术语"],
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_bundle"]["evidence_slot_package"]["missing_required_slot_ids"] == ["missing_required_slot"]
    assert data["precheck_result"]["execution_status"] == "needs_evidence"
    assert data["precheck_result"]["llm_required"] is False
    assert any(check["type"] == "evidence_slot_required_presence" for check in data["precheck_result"]["checks"])
    assert data["review_conclusion"]["status"] == "needs_evidence"
    assert data["review_conclusion"]["llm_required"] is False
    assert data["agent_trace"]["llm_skipped"] is True
    assert not isolated_config.exists()


def test_preview_missing_required_evidence_slot_does_not_require_llm_key(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "review_llm_api_key", "")
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-MISSING-SLOT-NO-LLM-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "植物措施缺证据无需 LLM",
            "evidence_scope": {"sections": ["植物措施"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "evidence_slots": [
                {
                    "id": "missing_required_slot",
                    "label": "必填但缺失的槽位",
                    "required": True,
                    "queries": ["植物措施 乔木"],
                    "expected_terms": ["不存在的必填证据术语"],
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["precheck_result"]["execution_status"] == "needs_evidence"
    assert data["review_conclusion"]["status"] == "needs_evidence"
    assert data["agent_trace"]["llm_skipped"] is True
    assert not isolated_config.exists()


def test_preview_without_evidence_blocker_still_requires_llm_key(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "review_llm_api_key", "")
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "enabled": True,
        },
    )

    assert response.status_code == 503
    assert "LLM" in response.json()["detail"]["message"]
    assert not isolated_config.exists()


def test_preview_project_composition_consistency_returns_structured_comparison(isolated_config, client: TestClient):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-003",
            "rule_id": "PROJECT-COMPOSITION-001",
            "executor_type_id": "cross_reference",
            "review_type": "项目组成一致性审查",
            "review_sub_type": "项目组成及建设内容与立项文件一致性",
            "evidence_scope": {
                "sections": ["项目概况"],
                "attachments": ["立项文件", "初步设计批复"],
            },
            "target_fields": ["项目组成", "建设内容", "总建筑面积", "地上建筑面积", "地下建筑面积"],
            "review_criteria": "读取项目概要章节的项目组成与建设内容，读取附件里的立项文件内容，判断它们是否一致。",
            "expected_result": "项目组成及建设内容应与立项文件或所处阶段的主体设计文件一致。",
            "failure_conditions": ["正文建设规模与立项或主体设计文件不一致"],
            "evidence_slots": [
                {
                    "id": "project_summary",
                    "label": "项目概要章节的项目组成与建设内容",
                    "required": True,
                    "queries": ["项目概况 建设内容 总建筑面积 地上建筑面积 地下建筑面积"],
                    "expected_terms": ["建设内容", "总建筑面积"],
                    "preferred_sections": ["项目概况"],
                },
                {
                    "id": "approval_or_design_attachment",
                    "label": "立项文件或主体设计附件内容",
                    "required": True,
                    "queries": ["初步设计批复 项目建筑面积 地上建筑面积 地下建筑面积"],
                    "expected_terms": ["初步设计", "建筑面积"],
                    "preferred_sections": ["附件", "初步设计批复"],
                },
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    comparison = data["evidence_bundle"]["project_composition_consistency"]
    assert comparison["status"] == "mismatch"
    assert comparison["body_source"]["chunk_id"] == "rag-project-body-001"
    assert comparison["body_source"]["anchors"][0]["block_id"] == "p10-b01"
    assert comparison["reference_source"]["chunk_id"] == "rag-project-approval-001"
    assert comparison["reference_source"]["material_type"] == "preliminary_design_reply"
    assert comparison["reference_source"]["anchors"][0]["block_id"] == "p136-b02"
    slot_package = data["evidence_bundle"]["evidence_slot_package"]
    assert slot_package["missing_required_slot_ids"] == []
    assert {slot["slot_id"] for slot in slot_package["slots"]} == {"project_summary", "approval_or_design_attachment"}
    assert all(slot["status"] == "matched" for slot in slot_package["slots"])
    fields = {field["field"]: field for field in comparison["field_comparisons"]}
    assert fields["above_ground_building_area"]["status"] == "match"
    assert fields["total_building_area"]["status"] == "mismatch"
    assert fields["total_building_area"]["body_value"] == 81700.84
    assert fields["total_building_area"]["reference_value"] == 80836.65
    assert fields["underground_building_area"]["status"] == "mismatch"
    precheck = data["precheck_result"]
    assert precheck["project_composition_consistency"]["status"] == "mismatch"
    assert any(check["type"] == "project_composition_consistency" for check in precheck["checks"])


def test_preview_earthwork_formula_check_uses_langextract_facts(isolated_config, client: TestClient):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-002",
            "rule_id": "EARTHWORK-BALANCE-001",
            "executor_type_id": "evidence_presence",
            "review_type": "土石方专项审查",
            "review_sub_type": "土石方平衡（含表土）完整性",
            "evidence_scope": {"sections": ["项目概况", "土石方平衡"], "tables": ["土石方平衡表"]},
            "target_fields": ["土石方", "挖方", "填方", "借方", "弃方"],
            "review_criteria": "读取项目概要章节的土石方平衡文字及表格数据，判断挖方、填方、借方、弃方是否平衡。",
            "expected_result": "土石方平衡应明确挖方、填方、借方、弃方和调配情况。",
            "evidence_slots": [
                {
                    "id": "earthwork_quantities",
                    "label": "土石方工程量",
                    "required": True,
                    "queries": ["土石方平衡 挖方 填方 借方 弃方"],
                    "expected_terms": ["挖方", "填方", "借方", "弃方"],
                }
            ],
            "formula_checks": [
                {
                    "id": "earthwork_total_balance",
                    "label": "土石方总量平衡",
                    "left_fields": ["excavation_volume", "borrow_volume"],
                    "right_fields": ["fill_volume", "spoil_volume"],
                    "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    "required": True,
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    results = data["evidence_bundle"]["formula_check_results"]
    assert results["source"] == "formula_checks"
    assert results["check_count"] == 1
    check = results["checks"][0]
    assert check["formula_check_id"] == "earthwork_total_balance"
    assert check["status"] == "pass"
    assert check["left_value"] == 12.0
    assert check["right_value"] == 12.0
    assert check["unit"] == "万m3"
    assert check["field_values"]["excavation_volume"]["fact_id"] == "fact-earthwork-excavation"
    assert data["evidence_bundle"]["evidence_slot_package"]["missing_required_slot_ids"] == []
    assert not isolated_config.exists()


def test_preview_formula_checks_use_full_langextract_facts_for_explicit_fields(isolated_config, client: TestClient):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-002",
            "rule_id": "EARTHWORK-FORMULA-FIELDS-001",
            "executor_type_id": "evidence_presence",
            "review_type": "土石方专项审查",
            "review_sub_type": "显式公式字段校验",
            "target_fields": ["土石方总量"],
            "review_criteria": "按显式 formula_checks 字段执行程序计算。",
            "expected_result": "显式公式字段应可从 LangExtract facts 中取数。",
            "formula_checks": [
                {
                    "id": "earthwork_total_balance",
                    "left_fields": ["excavation_volume", "borrow_volume"],
                    "right_fields": ["fill_volume", "spoil_volume"],
                    "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    "required": True,
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    check = response.json()["evidence_bundle"]["formula_check_results"]["checks"][0]
    assert check["status"] == "pass"
    assert set(check["field_values"]) == {
        "excavation_volume",
        "borrow_volume",
        "fill_volume",
        "spoil_volume",
    }
    assert response.json()["precheck_result"]["formula_check_results"]["check_count"] == 1
    assert not isolated_config.exists()


def test_preview_formula_failure_constrains_llm_pass_and_enters_prompt(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_prompt: dict = {}

    class PassingLLM:
        def invoke(self, messages):
            captured_prompt.update(json.loads(messages[-1].content))

            class Response:
                content = json.dumps(
                    {
                        "status": "pass",
                        "summary": "LLM 错误判断为通过。",
                        "actual_value": "LLM 未执行程序计算。",
                        "expected_value": "应由公式结果约束。",
                        "fix_suggestion": "",
                        "confidence": 90,
                        "next_action": "无",
                    },
                    ensure_ascii=False,
                )

            return Response()

    monkeypatch.setattr(review_agent_service, "get_llm", lambda: PassingLLM())

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-002",
            "rule_id": "EARTHWORK-FORMULA-FAIL-001",
            "executor_type_id": "evidence_presence",
            "review_type": "土石方专项审查",
            "review_sub_type": "公式失败状态约束",
            "target_fields": ["土石方", "挖方", "填方"],
            "review_criteria": "公式失败时 LLM 不得覆盖程序结论。",
            "expected_result": "挖方应等于填方。",
            "formula_checks": [
                {
                    "id": "excavation_equals_fill",
                    "left_fields": ["excavation_volume"],
                    "right_fields": ["fill_volume"],
                    "tolerance": {"absolute": 0.01, "unit": "万m3"},
                    "required": True,
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_bundle"]["formula_check_results"]["checks"][0]["status"] == "fail"
    assert data["precheck_result"]["formula_precheck"]["status"] == "issue"
    assert data["review_conclusion"]["status"] == "issue"
    assert "公式校验未通过" in data["review_conclusion"]["summary"]
    assert captured_prompt["formula_check_results"]["checks"][0]["status"] == "fail"
    assert captured_prompt["evidence_slot_package"]["source"] == "evidence_slots"
    assert not isolated_config.exists()


def test_preview_evidence_slot_retrieval_uses_candidate_top_k_not_rerank_top_n(
    isolated_config,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_top_k: list[int] = []

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        captured_top_k.append(top_k)
        return {
            "query": query,
            "retrieval_mode": "fake",
            "matches": [
                {
                    "chunk_id": "slot-candidate",
                    "document": "候选召回命中远端 chunk",
                    "metadata": {"page_start": 1, "page_end": 1, "section": "测试"},
                    "score": 0.5,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": 9},
                }
            ],
        }

    monkeypatch.setattr(settings, "rag_top_k", 50)
    monkeypatch.setattr(settings, "rag_rerank_top_n", 5)
    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)

    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "SLOT-TOPK-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据槽位核验",
            "review_sub_type": "槽位召回候选上限",
            "target_fields": ["植物措施"],
            "evidence_slots": [
                {
                    "id": "candidate_depth",
                    "required": True,
                    "queries": ["需要完整候选召回"],
                }
            ],
            "enabled": True,
        },
    )

    assert response.status_code == 200
    assert captured_top_k == [50]
    assert response.json()["evidence_bundle"]["evidence_slot_package"]["missing_required_slot_ids"] == []
    assert not isolated_config.exists()


def test_retrieval_debug_returns_non_persistent_matches_with_anchors(client: TestClient):
    preview_response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-TASK5-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "target_fields": ["植物措施", "乔木", "灌木"],
            "review_criteria": "核验植物措施章节是否说明乔木、灌木配置。",
            "expected_result": "植物措施配置完整且有表格支撑。",
            "enabled": True,
        },
    )
    assert preview_response.status_code == 200

    with client.app.state.TestingSessionLocal() as db:
        before_review_item_count = db.query(ReviewItem).count()

    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "植物措施 乔木 灌木", "top_k": 4, "use_rerank": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["query"] == "植物措施 乔木 灌木"
    assert data["matches"]
    first_match = data["matches"][0]
    assert first_match["chunk_id"] == "rag-plant-001"
    assert "乔木120株" in first_match["text"]
    assert first_match["page"] == 12
    assert first_match["page_end"] == 12
    assert first_match["section"] == "5 植物措施"
    assert first_match["bbox_count"] == 2
    assert first_match["block_ids"] == ["p12-b03", "p12-b04"]
    assert first_match["anchors"][0]["block_id"] == "p12-b03"
    assert first_match["final_rank"] == 1
    assert first_match["retrieval_sources"] == ["bm25", "rerank", "vector"]
    assert first_match["source_ranks"]["bm25"] == 1
    assert first_match["source_ranks"]["rerank"] == 1
    assert first_match["source_ranks"]["vector"] == 1
    assert data["trace"]["persisted"] is False
    assert data["trace"]["vector_available"] is True
    assert data["trace"]["retrieval_mode"] == "vector_bm25_neighbor_rerank"

    with client.app.state.TestingSessionLocal() as db:
        assert db.query(ReviewItem).count() == before_review_item_count


def test_retrieval_debug_can_run_evidence_slot_package(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    captured_top_k: list[int] = []

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        captured_top_k.append(top_k)
        return {
            "query": query,
            "retrieval_mode": "bm25_neighbor",
            "matches": [
                {
                    "chunk_id": f"debug-slot-{index}",
                    "document": f"植物措施 乔木 灌木 第 {index} 条证据",
                    "metadata": {"page_start": index, "page_end": index, "section": "植物措施"},
                    "score": 1.0 / index,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": index},
                }
                for index in range(1, 6)
            ],
            "vector_available": False,
            "bm25_available": True,
            "rerank_available": False,
        }

    monkeypatch.setattr(review_agent_service, "retrieve_for_query", fake_retrieve_for_query)

    with client.app.state.TestingSessionLocal() as db:
        before_review_item_count = db.query(ReviewItem).count()

    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={
            "evidence_slot": {
                "id": "debug_plant_slot",
                "label": "植物措施槽位调试",
                "required": True,
                "queries": ["植物措施 乔木 灌木"],
                "expected_terms": ["乔木", "灌木"],
                "min_matches": 2,
            },
            "use_vector": False,
            "use_bm25": True,
            "use_neighbors": True,
            "use_rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured_top_k == [50]
    assert data["status"] == "ready"
    assert data["query"] == "植物措施 乔木 灌木"
    package = data["evidence_slot_package"]
    assert package["slot_count"] == 1
    assert package["missing_required_slot_ids"] == []
    slot = package["slots"][0]
    assert slot["slot_id"] == "debug_plant_slot"
    assert slot["status"] == "matched"
    assert slot["min_matches"] == 2
    assert slot["candidate_top_k"] == 50
    assert slot["final_match_limit"] == 5
    assert slot["prompt_match_limit"] == 3
    assert slot["match_count"] == 5
    assert [match["chunk_id"] for match in slot["prompt_matches"]] == ["debug-slot-1", "debug-slot-2", "debug-slot-3"]
    assert [match["chunk_id"] for match in slot["trace_matches"]] == ["debug-slot-4", "debug-slot-5"]
    assert [match["chunk_id"] for match in data["matches"]] == [
        "debug-slot-1",
        "debug-slot-2",
        "debug-slot-3",
        "debug-slot-4",
        "debug-slot-5",
    ]
    assert data["trace"]["debug_mode"] == "evidence_slot"
    assert data["trace"]["top_k"] == 50
    assert data["trace"]["slot_top_k"] == 50
    assert data["trace"]["evidence_slot_defaults"]["candidate_top_k"] == 50
    assert data["trace"]["evidence_slot_defaults"]["final_top_k_per_slot"] == 5
    assert data["trace"]["evidence_slot_defaults"]["prompt_match_limit"] == 3
    assert data["trace"]["evidence_slot_defaults"]["min_matches"] == 1
    assert "vector_top_k" not in data["trace"]["evidence_slot_defaults"]
    assert data["trace"]["top_k_clamped"] is False
    assert data["trace"]["requested_use_bm25"] is True

    with client.app.state.TestingSessionLocal() as db:
        assert db.query(ReviewItem).count() == before_review_item_count


def test_retrieval_debug_query_uses_shared_default_top_k_when_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    captured_top_k: list[int] = []

    def fake_retrieve_for_query(chunks, query, top_k, **kwargs):
        captured_top_k.append(top_k)
        return {
            "query": query,
            "retrieval_mode": "bm25_neighbor",
            "matches": [
                {
                    "chunk_id": "debug-query-default",
                    "document": "植物措施 乔木 灌木 默认召回证据",
                    "metadata": {"page_start": 12, "page_end": 12, "section": "植物措施"},
                    "score": 1.0,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": 1},
                }
            ],
            "vector_available": False,
            "bm25_available": True,
            "rerank_available": False,
        }

    monkeypatch.setattr(retrieval_debug_service.rag_service, "retrieve_for_query", fake_retrieve_for_query)

    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={
            "query": "植物措施 乔木 灌木",
            "use_vector": False,
            "use_bm25": True,
            "use_neighbors": True,
            "use_rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured_top_k == [50]
    assert data["trace"]["top_k"] == 50
    assert data["trace"]["retrieval_defaults"]["candidate_top_k"] == 50
    assert data["trace"]["top_k_clamped"] is False


def test_retrieval_debug_degrades_to_bm25_when_vector_index_is_missing(client: TestClient):
    with client.app.state.TestingSessionLocal() as db:
        before_review_item_count = db.query(ReviewItem).count()

    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "植物措施 乔木 灌木", "top_k": 4, "use_rerank": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["matches"]
    assert data["matches"][0]["chunk_id"] == "rag-plant-001"
    assert data["matches"][0]["bm25_score"] is not None
    assert data["matches"][0]["vector_score"] is None
    assert data["matches"][0]["final_rank"] == 1
    assert data["matches"][0]["retrieval_sources"] == ["bm25"]
    assert data["matches"][0]["source_ranks"]["bm25"] == 1
    assert data["matches"][0]["source_ranks"].get("vector") is None
    assert data["matches"][0]["source_ranks"].get("rerank") is None
    assert data["trace"]["persisted"] is False
    assert data["trace"]["vector_available"] is False
    assert data["trace"]["bm25_available"] is True
    assert data["trace"]["rerank_available"] is False
    assert data["trace"]["retrieval_mode"] == "bm25_neighbor"

    with client.app.state.TestingSessionLocal() as db:
        assert db.query(ReviewItem).count() == before_review_item_count


def test_retrieval_debug_reports_unavailable_when_chunks_are_missing(client: TestClient):
    (client.app.state.artifact_dir / "review_chunks.json").unlink()
    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "植物措施 乔木 灌木", "top_k": 4, "use_rerank": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["reason"] == "review_chunks_missing"
    assert data["matches"] == []
    assert data["trace"]["persisted"] is False
    assert data["trace"]["bm25_available"] is False
    assert data["trace"]["vector_available"] is False
    assert data["trace"]["rerank_available"] is False


def test_retrieval_debug_rejects_oversized_query(client: TestClient):
    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "水" * 501, "top_k": 4, "use_rerank": True},
    )

    assert response.status_code == 422


def test_retrieval_debug_rejects_when_query_and_slot_are_missing(client: TestClient):
    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "", "use_vector": True, "use_bm25": True},
    )

    assert response.status_code == 400
    assert "query 或 evidence_slot" in response.json()["detail"]["message"]


def test_retrieval_debug_clamps_top_k_without_persisting(client: TestClient):
    with client.app.state.TestingSessionLocal() as db:
        before_review_item_count = db.query(ReviewItem).count()

    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={"query": "植物措施 乔木 灌木", "top_k": 999, "use_rerank": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace"]["top_k"] == 50
    assert data["trace"]["retrieval_defaults"]["candidate_top_k"] == 50
    assert data["trace"]["requested_top_k"] == 999
    assert data["trace"]["top_k_clamped"] is True
    assert data["trace"]["requested_use_rerank"] is False
    assert data["trace"]["rerank_available"] is False
    assert data["trace"]["persisted"] is False
    with client.app.state.TestingSessionLocal() as db:
        assert db.query(ReviewItem).count() == before_review_item_count


def test_retrieval_debug_can_isolate_vector_and_bm25_paths(client: TestClient):
    preview_response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-TASK5-001",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "target_fields": ["植物措施", "乔木", "灌木"],
            "review_criteria": "核验植物措施章节是否说明乔木、灌木配置。",
            "expected_result": "植物措施配置完整且有表格支撑。",
            "enabled": True,
        },
    )
    assert preview_response.status_code == 200

    vector_only = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={
            "query": "植物措施 乔木 灌木",
            "top_k": 4,
            "use_vector": True,
            "use_bm25": False,
            "use_neighbors": False,
            "use_rerank": False,
        },
    )
    assert vector_only.status_code == 200
    vector_data = vector_only.json()
    assert vector_data["status"] == "ready"
    assert vector_data["matches"]
    assert vector_data["matches"][0]["retrieval_sources"] == ["vector"]
    assert vector_data["matches"][0]["source_ranks"]["vector"] == 1
    assert vector_data["matches"][0]["source_ranks"].get("bm25") is None
    assert vector_data["trace"]["requested_use_vector"] is True
    assert vector_data["trace"]["requested_use_bm25"] is False
    assert vector_data["trace"]["requested_use_neighbors"] is False
    assert vector_data["trace"]["retrieval_mode"] == "vector"

    bm25_only = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={
            "query": "植物措施 乔木 灌木",
            "top_k": 4,
            "use_vector": False,
            "use_bm25": True,
            "use_neighbors": False,
            "use_rerank": False,
        },
    )
    assert bm25_only.status_code == 200
    bm25_data = bm25_only.json()
    assert bm25_data["status"] == "ready"
    assert bm25_data["matches"]
    assert bm25_data["matches"][0]["retrieval_sources"] == ["bm25"]
    assert bm25_data["matches"][0]["source_ranks"]["bm25"] == 1
    assert bm25_data["matches"][0]["source_ranks"].get("vector") is None
    assert bm25_data["trace"]["requested_use_vector"] is False
    assert bm25_data["trace"]["requested_use_bm25"] is True
    assert bm25_data["trace"]["requested_use_neighbors"] is False
    assert bm25_data["trace"]["retrieval_mode"] == "bm25"


def test_retrieval_debug_rejects_when_all_retrieval_paths_are_disabled(client: TestClient):
    response = client.post(
        "/api/v1/sessions/task5-session/retrieval-debug",
        json={
            "query": "植物措施 乔木 灌木",
            "use_vector": False,
            "use_bm25": False,
        },
    )

    assert response.status_code == 400
    assert "至少启用" in response.json()["detail"]["message"]


def test_preview_check_item_rag_query_is_driven_by_expert_brief(isolated_config, client: TestClient):
    with client.app.state.TestingSessionLocal() as db:
        before_review_item_count = db.query(ReviewItem).count()

    expert_brief = {
        "item_name": "唯一简报项名-植物措施-XYZ",
        "review_objective": "核查乔木、灌木配置是否在植物措施章节和植物措施工程量表中一致。",
        "evidence_instruction": "优先召回植物措施章节、植物措施工程量表，以及乔木和灌木工程量描述。",
        "judgement_basis": "以乔木、灌木数量和表格口径是否互相支撑作为判断依据。",
        "pass_condition": "植物措施工程量表列明乔木和灌木数量，且正文口径一致。",
        "issue_condition": "未见乔木或灌木数量，或植物措施工程量表与正文不一致。",
        "regulation_text": "植物措施审查口径：应核验乔木、灌木等植物措施配置及工程量表支撑。",
    }
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "rule_id": "PLANT-BRIEF-001",
            "executor_type_id": "evidence_presence",
            "review_type": "专家简报核验",
            "review_sub_type": "显式请求审查项-不应覆盖简报项名",
            "expert_brief": expert_brief,
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    bundle = data["evidence_bundle"]
    assert data["check_item"]["source_rule_snapshot"]["expert_brief"] == expert_brief
    for field in ["植物措施", "乔木", "灌木"]:
        assert field in data["check_item"]["target_fields"]
    assert data["check_item"]["failure_conditions"]
    assert expert_brief["evidence_instruction"] in data["check_item"]["evidence_scope"]["instructions"]
    assert expert_brief["regulation_text"].rstrip("。") in data["check_item"]["regulation_clauses"]
    assert bundle["source"] == "rag_agent"
    assert bundle["retrieval_matches"]
    assert bundle["retrieval_matches"][0]["chunk_id"] == "rag-plant-001"
    assert "乔木120株" in bundle["retrieval_matches"][0]["text"]
    assert "灌木800株" in bundle["retrieval_matches"][0]["text"]
    query = data["agent_trace"]["query"]
    assert "乔木" in query
    assert "灌木" in query
    assert "植物措施工程量表" in query
    assert expert_brief["item_name"] in query
    assert expert_brief["regulation_text"] in query
    assert any(
        item["source"] == "source_rule_snapshot.expert_brief.regulation_text"
        and expert_brief["regulation_text"] in item["text"]
        for item in bundle["regulation_context"]
    )
    assert not isolated_config.exists()
    assert review_config_service.list_check_item_specs() == []
    with client.app.state.TestingSessionLocal() as db:
        assert db.query(ReviewItem).count() == before_review_item_count


def test_preview_check_item_completes_without_langextract_facts(isolated_config, client: TestClient):
    (client.app.state.artifact_dir / "langextract_facts.json").unlink()
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "evidence_scope": {"sections": ["植物措施"], "tables": ["植物措施工程量表"]},
            "target_fields": ["植物措施", "乔木", "灌木"],
            "review_criteria": "核验植物措施章节是否说明乔木、灌木配置。",
            "expected_result": "植物措施配置完整且有表格支撑。",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_bundle"]["source"] == "rag_agent"
    assert data["evidence_bundle"]["structured_facts"] == []
    assert data["agent_trace"]["facts_available"] is False
    assert data["review_conclusion"]["status"] == "pass"
    assert review_config_service.list_check_item_specs() == []


def test_preview_check_item_returns_400_when_chunks_unavailable(isolated_config, client: TestClient, monkeypatch):
    (client.app.state.artifact_dir / "review_chunks.json").unlink()
    monkeypatch.setattr(review_agent_service, "parse_document", lambda path: [])
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "executor_type_id": "evidence_presence",
            "review_type": "证据存在性核验",
            "review_sub_type": "植物措施配置完整性",
            "enabled": True,
        },
    )

    assert response.status_code == 400
    assert "缺少可召回文档内容" in response.json()["detail"]["message"]


def test_preview_check_item_returns_503_when_agent_key_missing(isolated_config, client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "siliconflow_api_key", "")
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "task5-session",
            "topic_id": "scmc-010",
            "executor_type_id": "evidence_presence",
            "review_sub_type": "植物措施配置完整性",
            "enabled": True,
        },
    )

    assert response.status_code == 503
    assert "SILICONFLOW_API_KEY" in response.json()["detail"]["message"]


def test_preview_check_item_returns_404_for_missing_session(isolated_config, client: TestClient):
    response = client.post(
        "/api/v1/review-config/check-items/preview",
        json={
            "session_id": "missing-session",
            "topic_id": "scmc-010",
            "executor_type_id": "evidence_presence",
            "review_sub_type": "植物措施配置完整性",
        },
    )

    assert response.status_code == 404


def test_rule_topics_tolerate_unknown_executor_type_without_api_validation():
    topics = build_review_rule_topics(
        [],
        configured_check_items=[
            {
                "id": "unknown-executor-item",
                "topic_id": "scmc-010",
                "executor_type_id": "future_executor_type",
                "review_type": "未来执行器",
                "review_sub_type": "未知执行器兼容审查项",
                "enabled": True,
            }
        ],
    )

    plant = next(topic for topic in topics if topic["id"] == "scmc-010")
    item = next(item for item in plant["check_items"] if item["id"] == "unknown-executor-item")
    precheck = item["reasoning_process"]["executor_precheck"]

    assert item["status"] == "pending"
    assert precheck["executor_type_id"] == "future_executor_type"
    assert precheck["handler_id"] == "manual_basic"
    assert precheck["execution_status"] == "pending"
    assert precheck["checks"][0]["type"] == "manual_review_required"
