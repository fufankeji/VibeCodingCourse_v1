from pathlib import Path

from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.extracted_field import ExtractedField
from app.models.report import ReviewReport
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession


def build_contract_entry(db: Session, contract: Contract, session: ReviewSession | None) -> dict:
    job = _latest_parse_job(db, contract.id, session.id if session else None)
    retry = _retry_decision(job)
    base = {
        "latest_parse_job_status": job.status if job else None,
        "latest_parse_job_stage": job.stage if job else None,
        "latest_parse_job_error_code": job.error_code if job else None,
        "latest_parse_job_error_message": job.error_message if job else None,
        "retry_count": job.attempt_count if job else 0,
        "max_retries": job.max_attempts if job else 0,
        "can_retry_parse": retry["can_retry_parse"],
        "retry_block_reason": retry["retry_block_reason"],
        "can_view_result": False,
        "entry_route_type": None,
        "entry_action_label": "不可进入",
        "read_only": False,
    }
    if not session:
        return base

    state = session.state
    if state == "aborted":
        return {**base, **_aborted_entry(db, session)}
    if state == "parsed":
        return {
            **base,
            "entry_route_type": "parsing",
            "entry_action_label": "查看解析结果",
            "can_view_result": True,
        }
    if state == "parsing":
        return {**base, "entry_route_type": "parsing", "entry_action_label": "继续解析"}
    if state in {"scanning", "hitl_field_verify"}:
        return {**base, "entry_route_type": "fields", "entry_action_label": "查看字段"}
    if state == "hitl_medium_confirm":
        return {**base, "entry_route_type": "batch", "entry_action_label": "继续复核"}
    if state in {"hitl_pending", "hitl_high_risk"}:
        return {**base, "entry_route_type": "review", "entry_action_label": "继续评审"}
    if state in {"completed", "report_ready"}:
        return {**base, "entry_route_type": "report", "entry_action_label": "查看报告", "can_view_result": True}
    return {
        **base,
        "entry_route_type": "review",
        "entry_action_label": "查看任务",
    }


def _latest_parse_job(db: Session, contract_id: str, session_id: str | None) -> DocumentParseJob | None:
    query = db.query(DocumentParseJob)
    if session_id:
        query = query.filter(DocumentParseJob.session_id == session_id)
    else:
        query = query.filter(DocumentParseJob.contract_id == contract_id)
    return query.order_by(DocumentParseJob.created_at.desc()).first()


def _retry_decision(job: DocumentParseJob | None) -> dict:
    if not job:
        return {"can_retry_parse": False, "retry_block_reason": "PARSE_JOB_NOT_FOUND"}
    if job.status == "succeeded":
        return {"can_retry_parse": False, "retry_block_reason": "PARSE_ALREADY_SUCCEEDED"}
    if job.status == "running":
        return {"can_retry_parse": False, "retry_block_reason": "PARSE_JOB_RUNNING"}
    if job.attempt_count >= job.max_attempts:
        return {"can_retry_parse": False, "retry_block_reason": "PARSE_RETRY_EXHAUSTED"}
    if not Path(job.source_file_path).exists():
        return {"can_retry_parse": False, "retry_block_reason": "SOURCE_FILE_MISSING"}
    return {"can_retry_parse": True, "retry_block_reason": None}


def _aborted_entry(db: Session, session: ReviewSession) -> dict:
    if db.query(ReviewReport).filter(ReviewReport.session_id == session.id).first():
        return {
            "can_view_result": True,
            "entry_route_type": "report",
            "entry_action_label": "查看报告",
            "read_only": True,
        }
    if db.query(ReviewItem).filter(ReviewItem.session_id == session.id).first():
        return {
            "can_view_result": True,
            "entry_route_type": "review",
            "entry_action_label": "查看审查记录",
            "read_only": True,
        }
    if db.query(ExtractedField).filter(ExtractedField.session_id == session.id).first():
        return {
            "can_view_result": True,
            "entry_route_type": "fields",
            "entry_action_label": "查看字段记录",
            "read_only": True,
        }
    return {
        "can_view_result": False,
        "entry_route_type": "aborted",
        "entry_action_label": "查看中止记录",
        "read_only": True,
    }
