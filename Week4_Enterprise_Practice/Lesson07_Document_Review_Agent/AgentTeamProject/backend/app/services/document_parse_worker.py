"""Persistent document parse job worker."""

from __future__ import annotations

import asyncio
import json
import socket
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.sse import sse_manager
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.session import ReviewSession
from app.services import mineru_service

PDF_DOCX_TYPES = {"pdf", "docx"}
JOB_MAX_ATTEMPTS = 3
LOCK_TIMEOUT_SECONDS = 15 * 60
WORKER_POLL_SECONDS = 2
PROGRESS_PAYLOAD_KEYS = {
    "segment_index",
    "segment_count",
    "page_ranges",
    "page_start",
    "page_end_requested",
}


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
    if job.status == "running":
        raise DocumentParseError("PARSE_JOB_RUNNING", "解析任务正在执行，不能重复重试")
    if job.attempt_count >= job.max_attempts:
        raise DocumentParseError("PARSE_RETRY_EXHAUSTED", "解析重试次数已达上限")
    if not Path(job.source_file_path).exists():
        raise DocumentParseError("SOURCE_FILE_MISSING", "原始文件不存在，无法重新解析")

    now = datetime.utcnow()
    session.state = "parsing"
    session.completed_at = None
    session.updated_at = now
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if contract:
        contract.contract_status = "processing"
        contract.updated_at = now
        db.add(contract)
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
    next_attempt_count = job.attempt_count + 1
    timing = _timing_payload(job)
    attempt_exists = str(next_attempt_count) in (timing.get("attempts") or {})
    queued_started_at = now if attempt_exists else (job.created_at if next_attempt_count == 1 else job.next_run_at or now)
    job.status = "running"
    job.stage = "queued"
    job.locked_by = worker_id
    job.locked_at = now
    job.started_at = now
    job.attempt_count = next_attempt_count
    job.error_code = None
    job.error_message = None
    job.updated_at = now
    _record_stage_transition(job, "queued", now=queued_started_at)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def _run_claimed_job(db: Session, job: DocumentParseJob) -> None:
    await _publish(job, "parse_started", {"stage": job.stage})
    if _is_job_canceled(db, job.id):
        return
    try:
        _prepare_parse_artifact(db, job)
        if _is_job_canceled(db, job.id):
            return
        _mark_job_succeeded(db, job)
        await _publish(job, "parse_completed", {"state": "parsed"})
        await sse_manager.publish(job.session_id, "state_changed", {"session_id": job.session_id, "state": "parsed"})
    except DocumentParseError as exc:
        await _mark_job_failed(db, job, exc.error_code, str(exc), timeout=exc.timeout, event_type=exc.event_type)
    except mineru_service.MinerUAPIError as exc:
        await _mark_job_failed(db, job, exc.error_code, str(exc), timeout=exc.timeout)
    except Exception as exc:
        await _mark_job_failed(db, job, "PARSE_JOB_FAILED", str(exc), event_type="system_failure")


def _prepare_parse_artifact(db: Session, job: DocumentParseJob) -> str:
    if job.source_file_type == "json":
        job.result_json_path = job.source_file_path
        _transition_stage(db, job, "extracted")
        return job.source_file_path
    if job.source_file_type not in PDF_DOCX_TYPES:
        raise DocumentParseError("UNSUPPORTED_FILE_TYPE", f"不支持的解析文件类型: {job.source_file_type}")
    if not settings.mineru_token.strip():
        raise DocumentParseError("MINERU_TOKEN_MISSING", "MINERU_TOKEN is required")

    _transition_stage(db, job, "upload_url_requested")
    mineru_started = time.monotonic()
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
    _record_stage_transition(job, "extracted")
    _record_timing_metric(job, "mineru_total_duration_ms", int((time.monotonic() - mineru_started) * 1000))
    db.add(job)
    db.commit()
    _publish_progress_nowait(job)
    parse_path = artifacts.best_parse_path
    if parse_path is None:
        raise DocumentParseError("MINERU_RESULT_INVALID", "MinerU did not produce a parse artifact")
    return str(parse_path)


def _update_mineru_progress(db: Session, job_id: str, stage: str, values: dict[str, Any]) -> None:
    job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
    if not job:
        return
    job.stage = stage
    _record_stage_transition(job, stage)
    if values.get("batch_id"):
        job.mineru_batch_id = values["batch_id"]
    if values.get("task_id"):
        job.mineru_task_id = values["task_id"]
    for key, value in values.items():
        if key.endswith("_duration_ms") and isinstance(value, int | float):
            _record_timing_metric(job, key, int(value))
        elif key in PROGRESS_PAYLOAD_KEYS:
            _record_timing_metric(job, f"latest_{key}", value)
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    _publish_progress_nowait(job)


def _mark_job_succeeded(db: Session, job: DocumentParseJob) -> None:
    if _is_job_canceled(db, job.id):
        return
    job.status = "succeeded"
    job.stage = "completed"
    now = datetime.utcnow()
    _record_stage_transition(job, "completed", now=now)
    _finish_current_stage(job, now=now)
    job.locked_by = None
    job.locked_at = None
    job.completed_at = now
    job.updated_at = now
    session = db.query(ReviewSession).filter(ReviewSession.id == job.session_id).first()
    if session and session.state not in {"aborted", "canceled"}:
        session.state = "parsed"
        session.completed_at = None
        session.updated_at = now
        db.add(session)
    db.add(job)
    db.add(
        AuditLog(
            session_id=job.session_id,
            event_type="parse_completed",
            actor_id="system",
            actor_type="system",
            metadata_json=json.dumps({"job_id": job.id, "timing": _public_timing_payload(job)}, ensure_ascii=False),
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
    _finish_current_stage(job, now=now)
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
                    "timing": _public_timing_payload(job),
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
            "timing": _public_timing_payload(job),
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
        "timing": _public_timing_payload(job),
    }
    payload.update(data)
    await sse_manager.publish(job.session_id, event_type, payload)


def _publish_progress_nowait(job: DocumentParseJob) -> None:
    timing = _public_timing_payload(job)
    metrics = timing.get("metrics") or {}
    progress_payload = {
        "session_id": job.session_id,
        "job_id": job.id,
        "provider": job.provider,
        "stage": job.stage,
        "retry_count": job.attempt_count,
        "max_retries": job.max_attempts,
        "timing": timing,
    }
    for key in PROGRESS_PAYLOAD_KEYS:
        value = metrics.get(f"latest_{key}")
        if value is not None:
            progress_payload[key] = value
    if job.mineru_batch_id:
        progress_payload["batch_id"] = job.mineru_batch_id
    if job.mineru_task_id:
        progress_payload["task_id"] = job.mineru_task_id
    sse_manager.publish_nowait(
        job.session_id,
        "parse_progress",
        progress_payload,
    )


def _timing_payload(job: DocumentParseJob) -> dict[str, Any]:
    if not job.timing_json:
        return {"attempts": {}}
    try:
        payload = json.loads(job.timing_json)
    except Exception:
        return {"attempts": {}}
    return payload if isinstance(payload, dict) else {"attempts": {}}


def _public_timing_payload(job: DocumentParseJob) -> dict[str, Any]:
    payload = _timing_payload(job)
    attempt = _attempt_timing(payload, job)
    return {
        "attempt": attempt.get("attempt"),
        "stages": attempt.get("stages") or {},
        "metrics": attempt.get("metrics") or {},
        "started_at": attempt.get("started_at"),
        "completed_at": attempt.get("completed_at"),
        "duration_ms": attempt.get("duration_ms"),
    }


def _dump_timing_payload(job: DocumentParseJob, payload: dict[str, Any]) -> None:
    job.timing_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _iso(dt: datetime) -> str:
    return f"{dt.isoformat()}Z"


def _attempt_timing(payload: dict[str, Any], job: DocumentParseJob) -> dict[str, Any]:
    attempts = payload.setdefault("attempts", {})
    attempt_key = str(max(job.attempt_count, 1))
    attempt = attempts.setdefault(
        attempt_key,
        {
            "attempt": max(job.attempt_count, 1),
            "started_at": _iso(job.started_at or datetime.utcnow()),
            "stages": {},
            "metrics": {},
        },
    )
    attempt.setdefault("stages", {})
    attempt.setdefault("metrics", {})
    return attempt


def _record_stage_transition(job: DocumentParseJob, stage: str, *, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    payload = _timing_payload(job)
    attempt = _attempt_timing(payload, job)
    stages = attempt["stages"]
    current_stage = attempt.get("current_stage")
    if current_stage and current_stage != stage:
        current = stages.get(current_stage)
        if isinstance(current, dict) and not current.get("ended_at"):
            current["ended_at"] = _iso(now)
            started_at = _parse_iso(current.get("started_at"))
            if started_at:
                current["duration_ms"] = int((now - started_at).total_seconds() * 1000)

    entry = stages.setdefault(stage, {})
    entry.setdefault("started_at", _iso(now))
    entry["last_seen_at"] = _iso(now)
    entry["update_count"] = int(entry.get("update_count") or 0) + 1
    attempt["current_stage"] = stage
    attempt["updated_at"] = _iso(now)
    payload["updated_at"] = _iso(now)
    _dump_timing_payload(job, payload)


def _finish_current_stage(job: DocumentParseJob, *, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    payload = _timing_payload(job)
    attempt = _attempt_timing(payload, job)
    current_stage = attempt.get("current_stage")
    stages = attempt.get("stages") or {}
    current = stages.get(current_stage) if current_stage else None
    if isinstance(current, dict) and not current.get("ended_at"):
        current["ended_at"] = _iso(now)
        started_at = _parse_iso(current.get("started_at"))
        if started_at:
            current["duration_ms"] = int((now - started_at).total_seconds() * 1000)
    started_value = attempt.get("started_at")
    if not started_value and job.started_at:
        started_value = _iso(job.started_at)
    started = _parse_iso(started_value)
    if started:
        attempt["duration_ms"] = int((now - started).total_seconds() * 1000)
    attempt["completed_at"] = _iso(now)
    attempt.pop("current_stage", None)
    payload["updated_at"] = _iso(now)
    _dump_timing_payload(job, payload)


def _record_timing_metric(job: DocumentParseJob, key: str, value: Any) -> None:
    payload = _timing_payload(job)
    attempt = _attempt_timing(payload, job)
    attempt["metrics"][key] = value
    payload["updated_at"] = _iso(datetime.utcnow())
    _dump_timing_payload(job, payload)


def _record_pipeline_metrics(db: Session, job: DocumentParseJob, pipeline: dict[str, Any] | None) -> None:
    if not isinstance(pipeline, dict):
        return
    timings = pipeline.get("timings")
    if not isinstance(timings, dict):
        return
    for key, value in timings.items():
        if key.endswith("_duration_ms") and isinstance(value, int | float):
            _record_timing_metric(job, key, int(value))
    rag = pipeline.get("rag")
    manifest = rag.get("index_manifest") if isinstance(rag, dict) else {}
    if isinstance(manifest, dict):
        for key in ("vector_rebuild_duration_ms", "vector_total_duration_ms"):
            value = manifest.get(key)
            if isinstance(value, int | float):
                _record_timing_metric(job, key, int(value))
    db.add(job)
    db.commit()


def _transition_stage(db: Session, job: DocumentParseJob, stage: str) -> None:
    job.stage = stage
    _record_stage_transition(job, stage)
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    _publish_progress_nowait(job)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except Exception:
        return None
