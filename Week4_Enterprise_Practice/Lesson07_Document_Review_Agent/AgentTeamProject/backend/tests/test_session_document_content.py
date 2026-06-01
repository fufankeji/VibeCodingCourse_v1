import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import sessions as sessions_api
from app.database import Base
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.session import ReviewSession
from app.services import water_review_service


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_document_content_can_read_mineru_artifact_before_review_pipeline(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "page_size": [612, 792],
                        "para_blocks": [
                            {
                                "type": "title",
                                "index": 0,
                                "bbox": [10, 20, 100, 40],
                                "lines": [{"spans": [{"content": "测试水保方案"}]}],
                            },
                            {
                                "type": "text",
                                "index": 1,
                                "bbox": [10, 50, 300, 90],
                                "lines": [{"spans": [{"content": "项目区存在土石方平衡问题。"}]}],
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_review_document_content(session.id, db)

        assert result["source"] == "mineru_json"
        assert result["source_pdf_url"] == f"/api/v1/sessions/{session.id}/source-file"
        assert result["page_count"] == 1
        assert result["pages"][0]["blocks"][0]["text"] == "测试水保方案"
        assert result["pages"][0]["blocks"][1]["text"] == "项目区存在土石方平衡问题。"
    finally:
        db.close()


def test_document_content_can_read_mineru_artifact_for_aborted_session(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "type": "title",
                                "index": 0,
                                "lines": [{"spans": [{"content": "已中止方案仍可查看"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="aborted", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_review_document_content(session.id, db)

        assert result["source"] == "mineru_json"
        assert result["source_pdf_url"] == f"/api/v1/sessions/{session.id}/source-file"
        assert result["pages"][0]["blocks"][0]["text"] == "已中止方案仍可查看"
    finally:
        db.close()


def test_session_source_file_serves_original_pdf(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.commit()

        response = sessions_api.get_session_source_file(session.id, db)

        assert str(response.path) == str(source)
        assert response.media_type == "application/pdf"
        assert response.filename == source.name
    finally:
        db.close()


def test_session_source_file_rejects_non_pdf_contract(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.json"
    source.write_text("{}", encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="json",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            sessions_api.get_session_source_file(session.id, db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_document_content_maps_segment_asset_paths_to_session_asset_urls(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    asset = tmp_path / "mineru" / "segments" / "part-001" / "images" / "table.jpg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"image")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "type": "image",
                                "index": 1,
                                "image_path": "segments/part-001/images/table.jpg",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_review_document_content(session.id, db)
        image_path = result["pages"][0]["blocks"][0]["image_path"]

        assert image_path == f"/api/v1/sessions/{session.id}/assets/segments/part-001/images/table.jpg"
        response = sessions_api.get_session_asset(session.id, "segments/part-001/images/table.jpg", db)
        assert str(response.path).endswith("segments/part-001/images/table.jpg")
    finally:
        db.close()


def test_session_asset_rejects_path_traversal(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            sessions_api.get_session_asset(session.id, "../secret.jpg", db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_langextract_facts_endpoint_reads_water_review_artifacts(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    artifact_dir = parsed_json.parent / "water_review"
    artifact_dir.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    facts = [
        {
            "fact_id": "fact-project-001",
            "field_name": "project_name",
            "value": "测试项目",
            "normalized_value": "测试项目",
            "unit": "",
            "section": "综合说明",
            "chunk_id": "chunk-0001",
            "page_range": [2, 2],
            "source_text": "项目名称：测试项目",
            "confidence": 90,
            "bbox_list": [{"block_id": "p2-b1", "page": 2, "bbox": [1, 2, 3, 4]}],
        },
        {
            "fact_id": "fact-area-001",
            "field_name": "disturbed_area",
            "value": "1.2hm²",
            "normalized_value": "1.2",
            "unit": "hm²",
            "section": "项目概况",
            "chunk_id": "chunk-0002",
            "page_range": [8, 8],
            "source_text": "扰动面积1.2hm²",
            "confidence": 82,
            "bbox_list": [],
        },
    ]
    findings = [
        {
            "finding_id": "finding-area-001",
            "finding_type": "area_cross_chapter_conflict",
            "field_name": "disturbed_area",
            "description": "扰动面积跨章节口径不一致",
            "risk_level": "MEDIUM",
        }
    ]
    (artifact_dir / "langextract_facts.json").write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "langextract_fact_index.json").write_text(
        json.dumps({"fact_count": 2, "fields": ["project_name", "disturbed_area"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "cross_chapter_findings.json").write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_langextract_facts(session.id, db)

        assert result["available"] is True
        assert result["fact_count"] == 2
        assert result["finding_count"] == 1
        assert result["field_counts"] == {"disturbed_area": 1, "project_name": 1}
        assert result["facts"][0]["fact_id"] == "fact-project-001"
        assert result["cross_chapter_findings"][0]["finding_id"] == "finding-area-001"
    finally:
        db.close()


def test_review_pipeline_status_reads_cached_stage_artifacts(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    artifact_dir = parsed_json.parent / "water_review"
    artifact_dir.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    (artifact_dir / "parsed_blocks.json").write_text(json.dumps([{"block_id": "p1-b1"}]), encoding="utf-8")
    (artifact_dir / "review_chunks.json").write_text(json.dumps([{"chunk_id": "chunk-0001"}, {"chunk_id": "chunk-0002"}]), encoding="utf-8")
    (artifact_dir / "extracted_fields.json").write_text(json.dumps([{"field_name": "project_name"}]), encoding="utf-8")
    (artifact_dir / "langextract_facts.json").write_text(json.dumps([{"fact_id": "fact-1"}]), encoding="utf-8")
    (artifact_dir / "rag_index_manifest.json").write_text(json.dumps({"chunk_count": 2}), encoding="utf-8")
    (artifact_dir / "rag_retrievals.json").write_text(json.dumps([{"rule_id": "R1"}]), encoding="utf-8")
    (artifact_dir / "rag_issues.json").write_text(json.dumps([{"rule_id": "R1"}]), encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_review_pipeline_status(session.id, db)

        assert result["available"] is True
        assert result["artifact_dir"] == str(artifact_dir.resolve())
        by_id = {stage["id"]: stage for stage in result["stages"]}
        assert by_id["parsed_blocks"]["status"] == "completed"
        assert by_id["review_chunks"]["item_count"] == 2
        assert by_id["rag_issues"]["artifact_exists"] is True
    finally:
        db.close()


def test_review_pipeline_status_includes_latest_system_failure(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="scanning", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.add(
            AuditLog(
                session_id=session.id,
                event_type="system_failure",
                actor_id="system",
                actor_type="system",
                metadata_json=json.dumps(
                    {
                        "error_code": "RAG_REVIEW_FAILED",
                        "user_message": "规则审查模型调用失败：LLM 判定阶段返回异常或格式不符合要求。",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

        result = sessions_api.get_review_pipeline_status(session.id, db)

        assert result["last_failure"]["error_code"] == "RAG_REVIEW_FAILED"
        assert "规则审查模型调用失败" in result["last_failure"]["message"]
    finally:
        db.close()


def test_review_pipeline_status_marks_stale_running_stage_failed(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    artifact_dir = parsed_json.parent / "water_review"
    artifact_dir.mkdir()
    (artifact_dir / "pipeline_status.json").write_text(
        json.dumps(
            {
                "session_id": "stale-status",
                "updated_at": (datetime.utcnow() - timedelta(minutes=10)).isoformat(),
                "stages": [{"id": "langextract_facts", "status": "running"}],
                "timings": {},
                "cache_hits": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="scanning", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_review_pipeline_status(session.id, db)

        stage = next(stage for stage in result["stages"] if stage["id"] == "langextract_facts")
        assert stage["status"] == "failed"
        assert "超过 3 分钟没有更新" in stage["message"]
    finally:
        db.close()


def test_langextract_facts_endpoint_returns_unavailable_before_pipeline(tmp_path):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        result = sessions_api.get_langextract_facts(session.id, db)

        assert result["available"] is False
        assert result["fact_count"] == 0
        assert result["facts"] == []
        assert result["message"] == "LangExtract 证据事实尚未生成"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_start_review_runs_pipeline_from_mineru_artifact_after_parse(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        called: dict[str, str] = {}

        async def fake_extract_fields(session_id, text, db_arg, file_path=None):
            called["session_id"] = session_id
            called["file_path"] = file_path
            target = db_arg.query(ReviewSession).filter(ReviewSession.id == session_id).first()
            target.state = "scanning"
            db_arg.add(target)
            db_arg.commit()
            return {"timings": {"pipeline_total_duration_ms": 1}}

        monkeypatch.setattr(sessions_api.ocr_service, "extract_fields", fake_extract_fields)

        result = await sessions_api.start_review(session.id, db=db)

        assert called == {"session_id": session.id, "file_path": str(parsed_json)}
        assert result["state"] == "scanning"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_start_review_allows_stale_scanning_session_without_outputs(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    artifact_dir = parsed_json.parent / "water_review"
    artifact_dir.mkdir()
    (artifact_dir / "pipeline_status.json").write_text(
        json.dumps(
            {
                "session_id": "stale",
                "updated_at": (datetime.utcnow() - timedelta(minutes=30)).isoformat(),
                "stages": [{"id": "langextract_facts", "status": "running"}],
                "timings": {},
                "cache_hits": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(
            contract_id=contract.id,
            state="scanning",
            created_by="tester",
            updated_at=datetime.utcnow() - timedelta(minutes=30),
        )
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        called: dict[str, str] = {}

        async def fake_extract_fields(session_id, text, db_arg, file_path=None):
            called["session_id"] = session_id
            called["file_path"] = file_path
            target = db_arg.query(ReviewSession).filter(ReviewSession.id == session_id).first()
            target.state = "scanning"
            db_arg.add(target)
            db_arg.commit()
            return {"timings": {"pipeline_total_duration_ms": 1}}

        monkeypatch.setattr(sessions_api.ocr_service, "extract_fields", fake_extract_fields)

        result = await sessions_api.start_review(session.id, db=db)

        assert called == {"session_id": session.id, "file_path": str(parsed_json)}
        assert result["state"] == "scanning"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_start_review_error_includes_pipeline_failure_reason(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir(parents=True)
    parsed_json.write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    db = SessionLocal()
    try:
        contract = Contract(
            title="测试方案",
            original_filename=source.name,
            file_type="pdf",
            file_path=str(source),
            uploaded_by="tester",
        )
        db.add(contract)
        db.flush()
        session = ReviewSession(contract_id=contract.id, state="parsed", created_by="tester")
        db.add(session)
        db.flush()
        db.add(
            DocumentParseJob(
                session_id=session.id,
                contract_id=contract.id,
                source_file_path=str(source),
                source_file_type="pdf",
                provider="mineru",
                status="succeeded",
                stage="completed",
                result_json_path=str(parsed_json),
            )
        )
        db.commit()

        def fake_run_pipeline(file_path, artifact_dir, session_id):
            raise RuntimeError("LangExtract completed but produced no grounded facts")

        monkeypatch.setattr(water_review_service, "run_pipeline", fake_run_pipeline)

        with pytest.raises(HTTPException) as exc_info:
            await sessions_api.start_review(session.id, db=db)

        assert exc_info.value.status_code == 500
        assert "证据不足" in exc_info.value.detail["message"]
        assert "当前解析结果未抽取到可用于字段核验和规则审查的原文证据" in exc_info.value.detail["message"]
        assert "MinerU 解析结果已保留" in exc_info.value.detail["message"]
    finally:
        db.close()
