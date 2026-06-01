"""Persistent document parse job worker."""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.sse import sse_manager
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.session import ReviewSession
from app.services import mineru_service, ocr_service

PDF_DOCX_TYPES = {"pdf", "docx"}
JOB_MAX_ATTEMPTS = 3
LOCK_TIMEOUT_SECONDS = 15 * 60
WORKER_POLL_SECONDS = 2


class DocumentParseError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        timeout: bool = False,
        event_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.timeout = timeout
        self.event_type = event_type


def create_parse_job(
    db: Session,
    *,
    session_id: str,
    contract_id: str,
    source_file_path: str,
    source_file_type: str,
) -> DocumentParseJob:
    job = DocumentParseJob(
        session_id=session_id,
        contract_id=contract_id,
        source_file_path=source_file_path,
        source_file_type=source_file_type,
        provider="mineru" if source_file_type in PDF_DOCX_TYPES else "mineru_json",
        status="queued",
        stage="queued",
        max_attempts=JOB_MAX_ATTEMPTS,
        next_run_at=datetime.utcnow(),
    )
    db.add(job)
    return job


def reset_parse_job_for_retry(db: Session, session_id: str) -> DocumentParseJob:
    job = (
        db.query(DocumentParseJob)
        .filter(DocumentParseJob.session_id == session_id)
        .order_by(DocumentParseJob.created_at.desc())
        .first()
    )
    if not job:
        raise DocumentParseError("PARSE_JOB_NOT_FOUND", "解析任务不存在")
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise DocumentParseError("SESSION_NOT_FOUND", "评审会话不存在")

    now = datetime.utcnow()
    session.state = "parsing"
    session.updated_at = now
    job.status = "queued"
    job.stage = "queued"
    job.next_run_at = now
    job.locked_by = None
    job.locked_at = None
    job.error_code = None
    job.error_message = None
    job.updated_at = now
    db.add(session)
    db.add(job)
    db.flush()
    return job


def cancel_parse_jobs_for_session(db: Session, session_id: str, reason: str = "用户主动放弃") -> int:
    now = datetime.utcnow()
    jobs = (
        db.query(DocumentParseJob)
        .filter(
            DocumentParseJob.session_id == session_id,
            DocumentParseJob.status.in_(["queued", "running", "failed", "timeout"]),
        )
        .all()
    )
    for job in jobs:
        job.status = "canceled"
        job.locked_by = None
        job.locked_at = None
        job.next_run_at = None
        job.error_code = "USER_ABORTED"
        job.error_message = reason
        job.updated_at = now
        db.add(job)
    db.flush()
    return len(jobs)


def recover_stale_running_jobs(db: Session, stale_after_seconds: int = LOCK_TIMEOUT_SECONDS) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
    jobs = (
        db.query(DocumentParseJob)
        .filter(DocumentParseJob.status == "running", DocumentParseJob.locked_at < cutoff)
        .all()
    )
    for job in jobs:
        job.status = "queued"
        job.stage = "queued"
        job.locked_by = None
        job.locked_at = None
        job.next_run_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.add(job)
    db.commit()
    return len(jobs)


async def worker_loop(session_factory: Callable[[], Session], stop_event: asyncio.Event | None = None) -> None:
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    with session_factory() as db:
        recover_stale_running_jobs(db)
    while stop_event is None or not stop_event.is_set():
        processed = await process_next_job(session_factory, worker_id=worker_id)
        if not processed:
            await asyncio.sleep(WORKER_POLL_SECONDS)


async def process_next_job(session_factory: Callable[[], Session], worker_id: str) -> bool:
    db = session_factory()
    try:
        job = _claim_next_job(db, worker_id)
        if not job:
            return False
        await _run_claimed_job(db, job)
        return True
    finally:
        db.close()


def _claim_next_job(db: Session, worker_id: str) -> DocumentParseJob | None:
    now = datetime.utcnow()
    job = (
        db.query(DocumentParseJob)
        .join(ReviewSession, ReviewSession.id == DocumentParseJob.session_id)
        .filter(
            ReviewSession.state != "aborted",
            or_(
                DocumentParseJob.status == "queued",
                and_(
                    DocumentParseJob.status.in_(["failed", "timeout"]),
                    DocumentParseJob.attempt_count < DocumentParseJob.max_attempts,
                ),
            ),
            or_(DocumentParseJob.next_run_at.is_(None), DocumentParseJob.next_run_at <= now),
        )
        .order_by(DocumentParseJob.created_at.asc())
        .first()
    )
    if not job:
        return None
    job.status = "running"
    job.stage = "queued"
    job.locked_by = worker_id
    job.locked_at = now
    job.attempt_count += 1
    job.error_code = None
    job.error_message = None
    job.updated_at = now
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def _run_claimed_job(db: Session, job: DocumentParseJob) -> None:
    await _publish(job, "parse_started", {"stage": job.stage})
    if _is_job_canceled(db, job.id):
        return
    try:
        parse_path = _prepare_parse_artifact(db, job)
        if _is_job_canceled(db, job.id):
            return
        job.stage = "pipeline_running"
        db.add(job)
        db.commit()
        await _publish(job, "parse_progress", {"stage": job.stage})
        await ocr_service.extract_fields(job.session_id, "", db, file_path=parse_path)
        if _is_job_canceled(db, job.id):
            return
        db.refresh(job)
        session = db.query(ReviewSession).filter(ReviewSession.id == job.session_id).first()
        if session and session.state == "aborted":
            raise DocumentParseError(
                "PIPELINE_FAILED",
                "文档解析后处理失败",
                event_type="system_failure",
            )
        _mark_job_succeeded(db, job)
    except DocumentParseError as exc:
        await _mark_job_failed(db, job, exc.error_code, str(exc), timeout=exc.timeout, event_type=exc.event_type)
    except mineru_service.MinerUAPIError as exc:
        await _mark_job_failed(db, job, exc.error_code, str(exc), timeout=exc.timeout)
    except Exception as exc:
        await _mark_job_failed(db, job, "PIPELINE_FAILED", str(exc), event_type="system_failure")


def _prepare_parse_artifact(db: Session, job: DocumentParseJob) -> str:
    if job.source_file_type == "json":
        job.stage = "extracted"
        db.add(job)
        db.commit()
        return job.source_file_path
    if job.source_file_type not in PDF_DOCX_TYPES:
        raise DocumentParseError("UNSUPPORTED_FILE_TYPE", f"不支持的解析文件类型: {job.source_file_type}")
    if not settings.mineru_token.strip():
        raise DocumentParseError("MINERU_TOKEN_MISSING", "MINERU_TOKEN is required")

    job.stage = "upload_url_requested"
    db.add(job)
    db.commit()
    artifacts = mineru_service.parse_file_to_artifacts(
        job.source_file_path,
        Path(job.source_file_path).parent / "mineru",
        progress_callback=lambda stage, values: _update_mineru_progress(db, job.id, stage, values),
    )
    job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job.id).first() or job
    job.stage = "extracted"
    job.mineru_batch_id = artifacts.batch_id or job.mineru_batch_id
    job.mineru_task_id = artifacts.task_id or job.mineru_task_id
    job.result_zip_path = str(artifacts.zip_path) if artifacts.zip_path else None
    job.result_json_path = str(artifacts.json_path) if artifacts.json_path else None
    job.result_markdown_path = str(artifacts.markdown_path) if artifacts.markdown_path else None
    db.add(job)
    db.commit()
    parse_path = artifacts.best_parse_path
    if parse_path is None:
        raise DocumentParseError("MINERU_RESULT_INVALID", "MinerU did not produce a parse artifact")
    return str(parse_path)


def _update_mineru_progress(db: Session, job_id: str, stage: str, values: dict[str, str]) -> None:
    job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
    if not job:
        return
    job.stage = stage
    if values.get("batch_id"):
        job.mineru_batch_id = values["batch_id"]
    if values.get("task_id"):
        job.mineru_task_id = values["task_id"]
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()


def _mark_job_succeeded(db: Session, job: DocumentParseJob) -> None:
    if _is_job_canceled(db, job.id):
        return
    job.status = "succeeded"
    job.stage = "completed"
    job.locked_by = None
    job.locked_at = None
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.add(
        AuditLog(
            session_id=job.session_id,
            event_type="parse_completed",
            actor_id="system",
            actor_type="system",
            metadata_json=json.dumps({"job_id": job.id}, ensure_ascii=False),
        )
    )
    db.commit()


async def _mark_job_failed(
    db: Session,
    job: DocumentParseJob,
    error_code: str,
    message: str,
    *,
    timeout: bool = False,
    event_type: str | None = None,
) -> None:
    if _is_job_canceled(db, job.id):
        return
    now = datetime.utcnow()
    job.status = "timeout" if timeout else "failed"
    job.locked_by = None
    job.locked_at = None
    job.error_code = error_code
    job.error_message = message
    job.next_run_at = now + timedelta(seconds=30)
    job.updated_at = now
    session = db.query(ReviewSession).filter(ReviewSession.id == job.session_id).first()
    contract = db.query(Contract).filter(Contract.id == job.contract_id).first()
    if job.attempt_count >= job.max_attempts:
        if session:
            session.state = "aborted"
            session.updated_at = now
            db.add(session)
        if contract:
            contract.contract_status = "aborted"
            contract.updated_at = now
            db.add(contract)
    failure_event_type = event_type or ("parse_timeout" if timeout else "parse_failed")
    db.add(job)
    db.add(
        AuditLog(
            session_id=job.session_id,
            event_type=failure_event_type,
            actor_id="system",
            actor_type="system",
            metadata_json=json.dumps(
                {
                    "job_id": job.id,
                    "error_code": error_code,
                    "retry_count": job.attempt_count,
                    "max_retries": job.max_attempts,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    await _publish(
        job,
        failure_event_type,
        {
            "error_code": error_code,
            "message": message,
            "retry_count": job.attempt_count,
            "max_retries": job.max_attempts,
            "state": session.state if session else "parsing",
        },
    )


def _is_job_canceled(db: Session, job_id: str) -> bool:
    status = db.query(DocumentParseJob.status).filter(DocumentParseJob.id == job_id).scalar()
    return status == "canceled"


async def _publish(job: DocumentParseJob, event_type: str, data: dict) -> None:
    payload = {
        "session_id": job.session_id,
        "job_id": job.id,
        "provider": job.provider,
        "stage": job.stage,
        "retry_count": job.attempt_count,
        "max_retries": job.max_attempts,
    }
    payload.update(data)
    await sse_manager.publish(job.session_id, event_type, payload)
