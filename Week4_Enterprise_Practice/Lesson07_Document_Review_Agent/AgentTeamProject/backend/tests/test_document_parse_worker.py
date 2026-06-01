import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.session import ReviewSession
from app.services import document_parse_worker


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _make_contract_session_job(db, tmp_path, file_type="pdf", status="queued", attempts=0):
    source = tmp_path / f"original.{file_type}"
    source.write_bytes(b"%PDF- fake" if file_type == "pdf" else b"{}")
    contract = Contract(
        title="测试方案",
        original_filename=source.name,
        file_type=file_type,
        file_path=str(source),
        uploaded_by="tester",
    )
    db.add(contract)
    db.flush()
    session = ReviewSession(contract_id=contract.id, state="parsing", created_by="tester")
    db.add(session)
    db.flush()
    job = DocumentParseJob(
        session_id=session.id,
        contract_id=contract.id,
        source_file_path=str(source),
        source_file_type=file_type,
        provider="mineru" if file_type in {"pdf", "docx"} else "mineru_json",
        status=status,
        attempt_count=attempts,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    return contract, session, job


@pytest.mark.asyncio
async def test_worker_missing_mineru_token_marks_retryable_failed_without_aborting(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf")
    session_id = session.id
    job_id = job.id
    db.close()
    monkeypatch.setattr(document_parse_worker.settings, "mineru_token", "")

    await document_parse_worker.process_next_job(SessionLocal, worker_id="test-worker")

    db = SessionLocal()
    try:
        updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
        updated_session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
        assert updated_job.status == "failed"
        assert updated_job.error_code == "MINERU_TOKEN_MISSING"
        assert updated_job.attempt_count == 1
        assert updated_session.state == "parsing"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_aborts_session_after_max_attempts(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf", attempts=2)
    session_id = session.id
    job_id = job.id
    db.close()
    monkeypatch.setattr(document_parse_worker.settings, "mineru_token", "")

    await document_parse_worker.process_next_job(SessionLocal, worker_id="test-worker")

    db = SessionLocal()
    try:
        updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
        updated_session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
        assert updated_job.status == "failed"
        assert updated_job.attempt_count == 3
        assert updated_session.state == "aborted"
    finally:
        db.close()


def test_recover_stale_running_jobs_requeues_expired_lock(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, _, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="running")
    job.locked_by = "dead-worker"
    job.locked_at = datetime.utcnow() - timedelta(minutes=30)
    db.add(job)
    db.commit()

    recovered = document_parse_worker.recover_stale_running_jobs(db, stale_after_seconds=60)

    updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job.id).first()
    db.close()
    assert recovered == 1
    assert updated_job.status == "queued"
    assert updated_job.locked_by is None
    assert updated_job.locked_at is None


def test_reset_parse_job_for_retry_requeues_failed_job(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="failed", attempts=1)

    result = document_parse_worker.reset_parse_job_for_retry(db, session.id)

    updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job.id).first()
    updated_session = db.query(ReviewSession).filter(ReviewSession.id == session.id).first()
    db.close()
    assert result.id == job.id
    assert updated_job.status == "queued"
    assert updated_job.locked_by is None
    assert updated_job.next_run_at is not None
    assert updated_session.state == "parsing"


def test_claim_next_job_picks_retryable_failed_job(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, _, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="failed", attempts=1)
    job.next_run_at = datetime.utcnow() - timedelta(seconds=1)
    db.add(job)
    db.commit()

    claimed = document_parse_worker._claim_next_job(db, "test-worker")

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.attempt_count == 2
    db.close()


def test_claim_next_job_skips_exhausted_failed_job(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, _, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="failed", attempts=3)
    job.next_run_at = datetime.utcnow() - timedelta(seconds=1)
    db.add(job)
    db.commit()

    claimed = document_parse_worker._claim_next_job(db, "test-worker")

    assert claimed is None
    db.close()


def test_claim_next_job_skips_aborted_session_job(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, _ = _make_contract_session_job(db, tmp_path, file_type="pdf", status="queued")
    session.state = "aborted"
    db.add(session)
    db.commit()

    claimed = document_parse_worker._claim_next_job(db, "test-worker")

    assert claimed is None
    db.close()


def test_cancel_parse_jobs_for_session_marks_job_canceled_and_unclaimable(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="queued")

    canceled = document_parse_worker.cancel_parse_jobs_for_session(db, session.id, reason="用户主动放弃")
    claimed = document_parse_worker._claim_next_job(db, "test-worker")

    updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job.id).first()
    assert canceled == 1
    assert claimed is None
    assert updated_job.status == "canceled"
    assert updated_job.error_code == "USER_ABORTED"
    assert updated_job.locked_by is None
    assert updated_job.next_run_at is None
    db.close()


def test_update_mineru_progress_publishes_sse_event(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf", status="running", attempts=1)
    queue = asyncio.Queue()
    document_parse_worker.sse_manager._queues[session.id] = [queue]

    try:
        document_parse_worker._update_mineru_progress(
            db,
            job.id,
            "polling",
            {"batch_id": "batch-1", "task_id": "task-1"},
        )

        updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job.id).first()
        event = queue.get_nowait()
        payload = json.loads(event["data"])
        assert updated_job.stage == "polling"
        assert updated_job.mineru_batch_id == "batch-1"
        assert updated_job.mineru_task_id == "task-1"
        assert event["event"] == "parse_progress"
        assert payload["session_id"] == session.id
        assert payload["job_id"] == job.id
        assert payload["stage"] == "polling"
        assert payload["retry_count"] == 1
        assert payload["max_retries"] == 3
    finally:
        document_parse_worker.sse_manager._queues.pop(session.id, None)
        db.close()


def test_mark_job_succeeded_does_not_overwrite_canceled_job(tmp_path):
    SessionLocal = _session_factory()
    db1 = SessionLocal()
    _, _, job = _make_contract_session_job(db1, tmp_path, file_type="pdf", status="running")
    job_id = job.id

    db2 = SessionLocal()
    try:
        same_job = db2.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
        same_job.status = "canceled"
        same_job.error_code = "USER_ABORTED"
        db2.add(same_job)
        db2.commit()
    finally:
        db2.close()

    document_parse_worker._mark_job_succeeded(db1, job)

    db1.expire_all()
    updated_job = db1.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
    assert updated_job.status == "canceled"
    assert updated_job.error_code == "USER_ABORTED"
    db1.close()
