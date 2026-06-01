from pathlib import Path
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.extracted_field import ExtractedField
from app.models.report import ReviewReport
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.api.contracts import list_contracts
from app.services.contract_entry_service import build_contract_entry


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _make_contract_session(db, tmp_path, state="aborted"):
    source = tmp_path / "方案.pdf"
    source.write_bytes(b"%PDF- fake")
    contract = Contract(
        title="测试方案",
        original_filename=source.name,
        file_type="pdf",
        file_path=str(source),
        uploaded_by="tester",
        contract_status="aborted" if state == "aborted" else "processing",
    )
    db.add(contract)
    db.flush()
    session = ReviewSession(contract_id=contract.id, state=state, created_by="tester")
    db.add(session)
    db.flush()
    job = DocumentParseJob(
        session_id=session.id,
        contract_id=contract.id,
        source_file_path=str(source),
        source_file_type="pdf",
        provider="mineru",
        status="canceled" if state == "aborted" else "queued",
        attempt_count=1,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    return contract, session, job


def test_aborted_contract_with_report_enters_report_readonly(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, _ = _make_contract_session(db, tmp_path, state="aborted")
    db.add(ReviewReport(session_id=session.id, report_status="ready"))
    db.commit()

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "report"
    assert entry["entry_action_label"] == "查看报告"
    assert entry["can_view_result"] is True
    assert entry["read_only"] is True


def test_aborted_contract_with_review_items_enters_review_readonly(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, _ = _make_contract_session(db, tmp_path, state="aborted")
    db.add(
        ReviewItem(
            session_id=session.id,
            clause_text="测试条款",
            risk_level="HIGH",
            ai_finding="测试风险",
        )
    )
    db.commit()

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "review"
    assert entry["entry_action_label"] == "查看审查记录"
    assert entry["can_view_result"] is True
    assert entry["read_only"] is True


def test_aborted_contract_with_fields_enters_fields_readonly(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, _ = _make_contract_session(db, tmp_path, state="aborted")
    db.add(ExtractedField(session_id=session.id, field_name="project_name", field_value="测试项目"))
    db.commit()

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "fields"
    assert entry["entry_action_label"] == "查看字段记录"
    assert entry["can_view_result"] is True
    assert entry["read_only"] is True


def test_aborted_contract_without_artifacts_enters_abort_record_and_can_retry(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, _ = _make_contract_session(db, tmp_path, state="aborted")

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "aborted"
    assert entry["entry_action_label"] == "查看中止记录"
    assert entry["can_view_result"] is False
    assert entry["can_retry_parse"] is True
    assert entry["retry_count"] == 1
    assert entry["max_retries"] == 3


def test_aborted_contract_cannot_retry_when_source_file_missing(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, job = _make_contract_session(db, tmp_path, state="aborted")
    Path(job.source_file_path).unlink()

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "aborted"
    assert entry["can_retry_parse"] is False
    assert entry["retry_block_reason"] == "SOURCE_FILE_MISSING"


def test_parsed_contract_enters_parse_result_page(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, session, job = _make_contract_session(db, tmp_path, state="parsed")
    job.status = "succeeded"
    job.stage = "completed"
    db.add(job)
    db.commit()

    entry = build_contract_entry(db, contract, session)

    db.close()
    assert entry["entry_route_type"] == "parsing"
    assert entry["entry_action_label"] == "查看解析结果"
    assert entry["can_view_result"] is True
    assert entry["can_retry_parse"] is False


def test_list_contracts_exposes_entry_decision_fields(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, _, _ = _make_contract_session(db, tmp_path, state="aborted")

    response = list_contracts(cursor=None, limit=20, state=None, db=db)

    db.close()
    item = response.items[0]
    assert item.entry_route_type == "aborted"
    assert item.entry_action_label == "查看中止记录"
    assert item.can_retry_parse is True
    assert item.retry_count == 1
    assert item.max_retries == 3


def test_list_contracts_state_filter_uses_latest_session_only(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    contract, old_session, _ = _make_contract_session(db, tmp_path, state="aborted")
    old_session.created_at = datetime.utcnow() - timedelta(days=1)
    latest_session = ReviewSession(contract_id=contract.id, state="parsing", created_by="tester")
    db.add(old_session)
    db.add(latest_session)
    db.commit()

    aborted_response = list_contracts(cursor=None, limit=20, state="aborted", db=db)
    parsing_response = list_contracts(cursor=None, limit=20, state="parsing", db=db)

    db.close()
    assert aborted_response.total == 0
    assert aborted_response.items == []
    assert parsing_response.total == 1
    assert parsing_response.items[0].session_id == latest_session.id
    assert parsing_response.items[0].session_state == "parsing"
