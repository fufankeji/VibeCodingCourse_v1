import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.audit_log import AuditLog
from app.models.session import ReviewSession
from app.services import ocr_service, water_review_service


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.mark.asyncio
async def test_extract_fields_pipeline_failure_preserves_parsed_session_and_logs_context(monkeypatch, caplog):
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        session = ReviewSession(contract_id="contract-1", state="parsed", created_by="tester")
        db.add(session)
        db.commit()

        def fake_run_pipeline(file_path, artifact_dir, session_id):
            raise RuntimeError("vector store failed")

        monkeypatch.setattr(water_review_service, "run_pipeline", fake_run_pipeline)
        caplog.set_level(logging.ERROR, logger="app.services.ocr_service")

        result = await ocr_service.extract_fields(session.id, "", db, file_path="/tmp/parsed.json")

        updated_session = db.query(ReviewSession).filter(ReviewSession.id == session.id).first()
        audit = db.query(AuditLog).filter(AuditLog.session_id == session.id).first()
        metadata = json.loads(audit.metadata_json)
        assert result is None
        assert updated_session.state == "parsed"
        assert "water_review_pipeline_failed" in caplog.text
        assert session.id in caplog.text
        assert "/tmp/parsed.json" in caplog.text
        assert "vector store failed" in caplog.text
        assert metadata["error"] == "vector store failed"
        assert metadata["file_path"] == "/tmp/parsed.json"
        assert metadata["artifact_dir"] == "/tmp/water_review"
        assert metadata["failure_category"] == "pipeline_runtime_error"
        assert metadata["user_message"] == "数据清洗与向量审查运行异常，请查看后端日志定位具体堆栈。"
    finally:
        db.close()


@pytest.mark.parametrize(
    ("raw_error", "category", "expected_hint"),
    [
        (
            "LangExtract completed but produced no grounded facts",
            "evidence_insufficient",
            "证据不足",
        ),
        (
            "REVIEW_LLM_API_KEY or DEEPSEEK_API_KEY is required for LangExtract",
            "llm_config_missing",
            "缺少大模型配置",
        ),
        (
            "SILICONFLOW_API_KEY is required for RAG review",
            "vector_config_missing",
            "缺少向量服务配置",
        ),
        (
            "LangExtract extraction failed for all documents: []",
            "evidence_extraction_failed",
            "证据抽取服务失败",
        ),
        (
            "SiliconFlow embedding response shape is invalid",
            "vector_service_failed",
            "向量服务异常",
        ),
        (
            "DeepSeek rule adjudication failed: timeout",
            "review_llm_failed",
            "规则审查模型调用失败",
        ),
    ],
)
def test_pipeline_failure_classifier_maps_known_errors_to_user_messages(raw_error, category, expected_hint):
    result = ocr_service.classify_pipeline_failure(raw_error)

    assert result["failure_category"] == category
    assert expected_hint in result["user_message"]
