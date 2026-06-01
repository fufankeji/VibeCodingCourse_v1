import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import sessions as sessions_api
from app.database import Base
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
        assert result["page_count"] == 1
        assert result["pages"][0]["blocks"][0]["text"] == "测试水保方案"
        assert result["pages"][0]["blocks"][1]["text"] == "项目区存在土石方平衡问题。"
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
