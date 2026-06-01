import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.sse import sse_manager
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.schemas.session import (
    AbortRequest,
    ProgressSummary,
    ReviewSessionResponse,
    SessionRecoveryResponse,
)
from app.services import ocr_service, retrieval_debug_service, water_review_service
from app.services.contract_entry_service import build_contract_entry
from app.services.document_parse_worker import DocumentParseError, cancel_parse_jobs_for_session, reset_parse_job_for_retry
from app.services.water_review_parsers import parse_document

router = APIRouter()
ASSET_URL_PREFIX = "/api/v1/sessions"
ASSET_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
logger = logging.getLogger(__name__)
STALE_REVIEW_SCAN_AFTER = timedelta(minutes=3)


class RetrievalDebugRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    evidence_slot: dict[str, Any] | None = None
    top_k: int | None = Field(default=None, ge=1)
    use_vector: bool = True
    use_bm25: bool = True
    use_neighbors: bool = True
    use_rerank: bool = True


class StartReviewResponse(BaseModel):
    session_id: str
    state: str
    message: str


def _build_progress_summary(session: ReviewSession) -> ProgressSummary:
    total_high = session.total_high_risk
    decided_high = session.decided_high_risk
    pending = max(0, total_high - decided_high)
    total = total_high + session.total_medium_risk + session.total_low_risk
    completion_percent = round((decided_high / total_high * 100) if total_high > 0 else 0.0, 1)
    return ProgressSummary(
        total_high_risk=total_high,
        decided_high_risk=decided_high,
        total_medium_risk=session.total_medium_risk,
        total_low_risk=session.total_low_risk,
        pending_high_risk=pending,
        completion_percent=completion_percent,
    )


@router.get("/{session_id}", response_model=ReviewSessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()

    data = {
        "id": session.id,
        "contract_id": session.contract_id,
        "state": session.state,
        "hitl_subtype": session.hitl_subtype,
        "langgraph_thread_id": session.langgraph_thread_id,
        "is_scanned_document": session.is_scanned_document,
        "created_by": session.created_by,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
        "updated_at": session.updated_at,
        "progress_summary": _build_progress_summary(session),
    }
    if contract:
        data.update(build_contract_entry(db, contract, session))
    return ReviewSessionResponse(**data)


@router.get("/{session_id}/recovery", response_model=SessionRecoveryResponse)
def get_session_recovery(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    pending_high = max(0, session.total_high_risk - session.decided_high_risk)
    resumable = session.state in {"hitl_high_risk", "hitl_field_verify", "hitl_medium_confirm"}

    return SessionRecoveryResponse(
        session_id=session_id,
        state=session.state,
        last_updated=session.updated_at,
        pending_high_risk_count=pending_high,
        resumable=resumable,
        message="会话可恢复，继续上次审核进度" if resumable else "会话不在可恢复状态",
    )


@router.get("/{session_id}/document-content")
def get_review_document_content(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")

    artifact_dir = Path(contract.file_path).parent / "water_review"
    parsed_blocks_path = artifact_dir / "parsed_blocks.json"
    source = "parsed_blocks"
    parse_job = _latest_successful_parse_job(session_id, db)
    if parsed_blocks_path.exists():
        try:
            blocks = json.loads(parsed_blocks_path.read_text(encoding="utf-8"))
        except Exception:
            raise APIError.internal("解析文档内容读取失败")
    else:
        blocks, source = _load_mineru_document_blocks(session_id, db, parse_job)

    if not isinstance(blocks, list):
        raise APIError.internal("解析文档内容格式错误")

    normalized_blocks = [_normalize_document_block(block, index) for index, block in enumerate(blocks)]
    _map_document_asset_urls(normalized_blocks, session_id, parse_job)
    pages: dict[int, list[dict[str, Any]]] = {}
    for block in normalized_blocks:
        pages.setdefault(block["page"], []).append(block)

    ordered_pages = [
        {"page_number": page, "blocks": page_blocks}
        for page, page_blocks in sorted(pages.items(), key=lambda item: item[0])
    ]

    return {
        "session_id": session_id,
        "contract_id": contract.id,
        "title": contract.title,
        "file_type": contract.file_type,
        "source": source,
        "source_pdf_url": _source_pdf_url(session_id, contract),
        "page_count": max(pages) if pages else 0,
        "outline": _build_document_outline(normalized_blocks),
        "pages": ordered_pages,
    }


@router.get("/{session_id}/langextract-facts")
def get_langextract_facts(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")

    job = _latest_successful_parse_job(session_id, db)
    artifact_dir = _latest_water_review_artifact_dir(contract, job)
    if not artifact_dir:
        return _empty_langextract_facts(session_id, contract.id, "LangExtract 证据事实尚未生成")

    facts_path = artifact_dir / "langextract_facts.json"
    if not facts_path.exists():
        return _empty_langextract_facts(session_id, contract.id, "LangExtract 证据事实尚未生成")

    facts = _load_json_list(facts_path, "LangExtract 证据事实读取失败")
    fact_index = _load_json_object(artifact_dir / "langextract_fact_index.json")
    findings = _load_json_list(artifact_dir / "cross_chapter_findings.json", "跨章节核验线索读取失败")
    field_counts = Counter(str(fact.get("field_name") or "") for fact in facts if isinstance(fact, dict))
    field_counts.pop("", None)

    return {
        "session_id": session_id,
        "contract_id": contract.id,
        "available": True,
        "source": "water_review_artifacts",
        "message": "LangExtract 证据事实已生成",
        "fact_count": len(facts),
        "finding_count": len(findings),
        "field_counts": dict(sorted(field_counts.items())),
        "fact_index": fact_index,
        "facts": facts,
        "cross_chapter_findings": findings,
    }


@router.get("/{session_id}/review-pipeline-status")
def get_review_pipeline_status(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")

    job = _latest_successful_parse_job(session_id, db)
    artifact_dir = _latest_water_review_artifact_dir(contract, job)
    if not artifact_dir:
        parse_artifact, _ = _best_parse_artifact(job)
        if parse_artifact:
            artifact_dir = parse_artifact.parent / "water_review"
        elif contract.file_path:
            artifact_dir = Path(contract.file_path).parent / "water_review"
    review_item_count = db.query(ReviewItem).filter(ReviewItem.session_id == session_id).count()
    status = water_review_service.build_pipeline_status(session_id, artifact_dir, review_item_count=review_item_count)
    if session.state == "scanning" and review_item_count == 0 and not _pipeline_status_is_recent(status):
        for stage in status.get("stages", []):
            if isinstance(stage, dict) and stage.get("status") == "running":
                stage["status"] = "failed"
                stage["message"] = "该阶段超过 3 分钟没有更新，后端任务可能已中断；可以重新启动清洗与审查。"
    latest_failure = _latest_system_failure_payload(session_id, db)
    if latest_failure:
        status["last_failure"] = latest_failure
    return status


@router.get("/{session_id}/assets/{asset_path:path}")
def get_session_asset(session_id: str, asset_path: str, db: Session = Depends(get_db)) -> FileResponse:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")
    job = _latest_successful_parse_job(session_id, db)
    root = _parse_artifact_root(job)
    target = _resolve_session_asset(root, asset_path)
    return FileResponse(target)


@router.get("/{session_id}/source-file")
def get_session_source_file(session_id: str, db: Session = Depends(get_db)) -> FileResponse:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")
    target = _resolve_source_pdf(contract)
    return FileResponse(
        target,
        media_type="application/pdf",
        filename=contract.original_filename or target.name,
        headers={"Content-Disposition": f'inline; filename="{quote(contract.original_filename or target.name)}"'},
    )


@router.post("/{session_id}/retrieval-debug")
def run_retrieval_debug(
    session_id: str,
    payload: RetrievalDebugRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return retrieval_debug_service.run_retrieval_debug(
            session_id,
            payload.query,
            db,
            evidence_slot=payload.evidence_slot,
            top_k=payload.top_k,
            use_vector=payload.use_vector,
            use_bm25=payload.use_bm25,
            use_neighbors=payload.use_neighbors,
            use_rerank=payload.use_rerank,
        )
    except retrieval_debug_service.RetrievalDebugBadRequest as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.post("/{session_id}/start-review", response_model=StartReviewResponse)
async def start_review(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    job = _latest_successful_parse_job(session_id, db)
    artifact_path, _ = _best_parse_artifact(job)
    if not artifact_path:
        raise APIError.not_found("ParsedDocument")
    if session.state != "parsed":
        if not _is_restartable_stale_review_session(session, artifact_path, db):
            raise APIError.session_state_invalid(session.state, "parsed")
        logger.warning(
            "start_review_recovering_stale_scanning session_id=%s contract_id=%s previous_updated_at=%s",
            session_id,
            session.contract_id,
            session.updated_at,
        )
        session.state = "parsed"
        session.hitl_subtype = None
        db.commit()
        db.refresh(session)

    logger.info(
        "start_review_requested session_id=%s contract_id=%s job_id=%s artifact_path=%s",
        session_id,
        session.contract_id,
        job.id if job else "",
        artifact_path,
    )
    pipeline = await ocr_service.extract_fields(session_id, "", db, file_path=str(artifact_path))
    db.refresh(session)
    if pipeline is None:
        reason = _latest_system_failure_reason(session_id, db)
        logger.error(
            "start_review_failed session_id=%s contract_id=%s job_id=%s artifact_path=%s reason=%s",
            session_id,
            session.contract_id,
            job.id if job else "",
            artifact_path,
            reason or "",
        )
        message = "数据清洗与向量审查失败"
        if reason:
            message = f"{message}：{reason}"
        raise APIError.internal(f"{message}，MinerU 解析结果已保留")

    logger.info(
        "start_review_succeeded session_id=%s contract_id=%s job_id=%s state=%s",
        session_id,
        session.contract_id,
        job.id if job else "",
        session.state,
    )
    return {
        "session_id": session_id,
        "state": session.state,
        "message": "数据清洗与向量审查已启动",
    }


def _normalize_document_block(block: Any, index: int) -> dict[str, Any]:
    data = block if isinstance(block, dict) else {}
    text = str(data.get("text") or "").strip()
    page = _safe_int(data.get("page"), 1)
    block_id = str(data.get("block_id") or f"block-{index + 1:04d}")
    block_type = str(data.get("type") or "paragraph")
    bbox = data.get("bbox") if isinstance(data.get("bbox"), list) else []
    return {
        "block_id": block_id,
        "page": page,
        "type": block_type,
        "text": text,
        "html": str(data.get("html") or ""),
        "image_path": str(data.get("image_path") or ""),
        "bbox": bbox,
        "section_hint": str(data.get("section_hint") or ""),
    }


def _load_mineru_document_blocks(
    session_id: str,
    db: Session,
    job: DocumentParseJob | None = None,
) -> tuple[list[dict[str, Any]], str]:
    job = job or _latest_successful_parse_job(session_id, db)
    for path, source in _parse_artifact_candidates(job):
        try:
            blocks = parse_document(str(path))
        except Exception:
            raise APIError.internal("MinerU 解析结果读取失败")
        return [asdict(block) for block in blocks], source

    raise APIError.not_found("ParsedDocument")


def _map_document_asset_urls(blocks: list[dict[str, Any]], session_id: str, job: DocumentParseJob | None) -> None:
    root = _parse_artifact_root(job)
    if not root:
        return
    for block in blocks:
        image_path = str(block.get("image_path") or "").strip()
        if not image_path:
            continue
        block["image_path"] = _asset_url_for_image_path(session_id, root, image_path)


def _asset_url_for_image_path(session_id: str, root: Path, image_path: str) -> str:
    if image_path.startswith(("http://", "https://", f"{ASSET_URL_PREFIX}/")):
        return image_path
    try:
        if Path(image_path).is_absolute():
            relative = Path(image_path).resolve().relative_to(root.resolve()).as_posix()
            _resolve_session_asset(root, relative)
        else:
            relative = image_path.lstrip("/")
            _resolve_session_asset(root, relative)
    except Exception:
        return image_path
    return f"{ASSET_URL_PREFIX}/{session_id}/assets/{quote(relative, safe='/')}"


def _source_pdf_url(session_id: str, contract: Contract) -> str:
    try:
        _resolve_source_pdf(contract)
    except Exception:
        return ""
    return f"{ASSET_URL_PREFIX}/{session_id}/source-file"


def _resolve_source_pdf(contract: Contract) -> Path:
    if str(contract.file_type or "").lower() != "pdf":
        raise APIError.not_found("SourcePdf")
    path = Path(contract.file_path or "")
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pdf":
        raise APIError.not_found("SourcePdf")
    return path.resolve()


def _parse_artifact_root(job: DocumentParseJob | None) -> Path | None:
    if not job:
        return None
    for raw_path in (job.result_json_path, job.result_markdown_path):
        if raw_path:
            path = Path(raw_path)
            if path.exists():
                return path.parent.resolve()
    return None


def _resolve_session_asset(root: Path | None, asset_path: str) -> Path:
    if not root:
        raise APIError.not_found("ParsedDocumentAsset")
    clean_path = asset_path.lstrip("/")
    if not clean_path:
        raise APIError.not_found("ParsedDocumentAsset")
    if Path(clean_path).suffix.lower() not in ASSET_SUFFIXES:
        raise APIError.not_found("ParsedDocumentAsset")
    root_resolved = root.resolve()
    target = (root_resolved / clean_path).resolve()
    if target == root_resolved or root_resolved not in target.parents or not target.is_file():
        raise APIError.not_found("ParsedDocumentAsset")
    return target


def _latest_successful_parse_job(session_id: str, db: Session) -> DocumentParseJob | None:
    return (
        db.query(DocumentParseJob)
        .filter(
            DocumentParseJob.session_id == session_id,
            DocumentParseJob.status == "succeeded",
        )
        .order_by(DocumentParseJob.completed_at.desc().nullslast(), DocumentParseJob.created_at.desc())
        .first()
    )


def _best_parse_artifact(job: DocumentParseJob | None) -> tuple[Path | None, str]:
    for path, source in _parse_artifact_candidates(job):
        return path, source
    return None, ""


def _parse_artifact_candidates(job: DocumentParseJob | None) -> list[tuple[Path, str]]:
    if not job:
        return []
    raw_candidates: list[tuple[str | None, str]] = [
        (job.result_json_path, "mineru_json"),
        (job.result_markdown_path, "mineru_markdown"),
    ]
    if job.source_file_type == "json":
        raw_candidates.append((job.source_file_path, "mineru_json"))

    candidates: list[tuple[Path, str]] = []
    for raw_path, source in raw_candidates:
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.exists():
            candidates.append((path, source))
    return candidates


def _latest_water_review_artifact_dir(contract: Contract, job: DocumentParseJob | None) -> Path | None:
    candidates: list[Path] = []
    for path, _ in _parse_artifact_candidates(job):
        candidates.append(path.parent / "water_review")
    if contract.file_path:
        candidates.append(Path(contract.file_path).parent / "water_review")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_dir():
            return resolved
    return None


def _empty_langextract_facts(session_id: str, contract_id: str, message: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "contract_id": contract_id,
        "available": False,
        "source": "water_review_artifacts",
        "message": message,
        "fact_count": 0,
        "finding_count": 0,
        "field_counts": {},
        "fact_index": {},
        "facts": [],
        "cross_chapter_findings": [],
    }


def _load_json_list(path: Path, error_message: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise APIError.internal(error_message)
    if not isinstance(data, list):
        raise APIError.internal(error_message)
    return [item for item in data if isinstance(item, dict)]


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _latest_system_failure_reason(session_id: str, db: Session) -> str:
    metadata = _latest_system_failure_payload(session_id, db)
    if not metadata:
        return ""
    reason = str(metadata.get("user_message") or metadata.get("error") or "").strip()
    return reason[:500]


def _latest_system_failure_payload(session_id: str, db: Session) -> dict[str, Any]:
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id, AuditLog.event_type == "system_failure")
        .order_by(AuditLog.occurred_at.desc())
        .first()
    )
    if not audit or not audit.metadata_json:
        return {}
    try:
        metadata = json.loads(audit.metadata_json)
    except Exception:
        return {}
    if not isinstance(metadata, dict):
        return {}
    payload = {key: value for key, value in metadata.items() if isinstance(key, str)}
    payload["occurred_at"] = audit.occurred_at.isoformat() if audit.occurred_at else ""
    if "message" not in payload:
        payload["message"] = str(payload.get("user_message") or payload.get("error") or "").strip()[:500]
    return payload


def _is_restartable_stale_review_session(session: ReviewSession, artifact_path: Path, db: Session) -> bool:
    if session.state != "scanning":
        return False
    if session.updated_at and datetime.utcnow() - session.updated_at < STALE_REVIEW_SCAN_AFTER:
        return False
    review_item_count = db.query(ReviewItem).filter(ReviewItem.session_id == session.id).count()
    if review_item_count > 0:
        return False
    status = water_review_service.build_pipeline_status(
        session.id,
        artifact_path.parent / "water_review",
        review_item_count=review_item_count,
    )
    stages = status.get("stages") if isinstance(status, dict) else []
    has_running_stage = any(isinstance(stage, dict) and stage.get("status") == "running" for stage in stages)
    if has_running_stage and _pipeline_status_is_recent(status):
        return False
    return True


def _pipeline_status_is_recent(status: dict[str, Any]) -> bool:
    updated_at = str(status.get("updated_at") or "")
    if not updated_at:
        return False
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is not None:
        return datetime.now(parsed.tzinfo) - parsed < STALE_REVIEW_SCAN_AFTER
    return datetime.utcnow() - parsed < STALE_REVIEW_SCAN_AFTER


def _build_document_outline(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for block in blocks:
        text = block["text"]
        if block["type"] != "title" or not text:
            continue
        if text in {"目 录", "附件：", "附图："}:
            continue
        if "....." in text:
            continue
        page = block["page"]
        level = _outline_level(text)
        if page <= 7 and level > 1:
            continue
        key = (text, page)
        if key in seen:
            continue
        seen.add(key)
        outline.append(
            {
                "id": block["block_id"],
                "title": text,
                "page_number": page,
                "level": level,
            }
        )
    return outline[:160]


def _outline_level(text: str) -> int:
    import re

    match = re.match(r"^(\d+(?:\.\d+)*)\s*", text)
    if not match:
        return 1
    return min(4, match.group(1).count(".") + 1)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


@router.get("/{session_id}/rule-topics")
def get_review_rule_topics(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    from app.services.water_review_service import load_rule_set
    from app.services.review_rule_schema import build_review_rule_topics
    from app.services.review_config_service import list_check_item_specs

    review_items = (
        db.query(ReviewItem)
        .filter(ReviewItem.session_id == session_id)
        .order_by(ReviewItem.created_at.asc())
        .all()
    )
    return {
        "session_id": session_id,
        "source": "session_items",
        "topics": build_review_rule_topics(
            load_rule_set(),
            review_items,
            configured_check_items=list_check_item_specs(),
        ),
    }


@router.post("/{session_id}/retry-parse")
async def retry_parse(
    session_id: str,
    x_user_id: str = Header(default="anonymous", alias="X-User-ID"),
    db: Session = Depends(get_db),
):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    if session.state not in {"parsing", "aborted"}:
        raise APIError.session_state_invalid(session.state, "parsing/aborted")

    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")

    now = datetime.utcnow()
    try:
        job = reset_parse_job_for_retry(db, session_id)
    except DocumentParseError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": exc.error_code,
                "message": str(exc),
                "request_id": "",
            },
        ) from exc
    except Exception as exc:
        raise APIError.bad_request(str(exc)) from exc

    audit = AuditLog(
        session_id=session_id,
        event_type="retry_parse",
        actor_id=x_user_id,
        actor_type="user",
        occurred_at=now,
        metadata_json=json.dumps({"contract_id": contract.id, "parse_job_id": job.id}),
    )
    db.add(audit)
    db.commit()

    return {
        "session_id": session_id,
        "job_id": job.id,
        "state": "parsing",
        "retry_count": job.attempt_count,
        "max_retries": job.max_attempts,
        "message": "重新解析已入队",
    }


@router.post("/{session_id}/abort")
async def abort_session(
    session_id: str,
    body: Optional[AbortRequest] = None,
    x_user_id: str = Header(default="anonymous", alias="X-User-ID"),
    db: Session = Depends(get_db),
):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    if session.state in {"report_ready", "aborted"}:
        raise APIError.session_state_invalid(session.state, "非 report_ready/aborted 状态")

    now = datetime.utcnow()
    session.state = "aborted"
    session.completed_at = now
    session.updated_at = now
    db.add(session)

    # Update contract status
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if contract:
        contract.contract_status = "aborted"
        contract.updated_at = now
        db.add(contract)

    reason = (body.reason if body and body.reason else "") or "用户主动放弃"
    canceled_parse_jobs = cancel_parse_jobs_for_session(db, session_id, reason=reason)
    audit = AuditLog(
        session_id=session_id,
        event_type="session_aborted",
        actor_id=x_user_id,
        actor_type="user",
        occurred_at=now,
        metadata_json=json.dumps({"reason": reason, "canceled_parse_jobs": canceled_parse_jobs}),
    )
    db.add(audit)
    db.commit()

    await sse_manager.publish(
        session_id,
        "session_aborted",
        {"session_id": session_id, "reason": reason},
    )
    await sse_manager.publish(
        session_id,
        "state_changed",
        {"session_id": session_id, "state": "aborted"},
    )

    return {"session_id": session_id, "state": "aborted", "message": "审核已放弃"}
