import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.sse import sse_manager
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.schemas.session import (
    AbortRequest,
    ProgressSummary,
    ReviewSessionResponse,
    SessionRecoveryResponse,
)
from app.services import retrieval_debug_service

router = APIRouter()


class RetrievalDebugRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=20)
    use_rerank: bool = True


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
    if not parsed_blocks_path.exists():
        raise APIError.not_found("ParsedDocument")

    try:
        blocks = json.loads(parsed_blocks_path.read_text(encoding="utf-8"))
    except Exception:
        raise APIError.internal("解析文档内容读取失败")

    if not isinstance(blocks, list):
        raise APIError.internal("解析文档内容格式错误")

    normalized_blocks = [_normalize_document_block(block, index) for index, block in enumerate(blocks)]
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
        "source": "parsed_blocks",
        "page_count": max(pages) if pages else 0,
        "outline": _build_document_outline(normalized_blocks),
        "pages": ordered_pages,
    }


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
            top_k=payload.top_k,
            use_rerank=payload.use_rerank,
        )
    except retrieval_debug_service.RetrievalDebugBadRequest as exc:
        raise APIError.bad_request(str(exc)) from exc


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
        "bbox": bbox,
        "section_hint": str(data.get("section_hint") or ""),
    }


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

    # Reset state
    now = datetime.utcnow()
    session.state = "parsing"
    session.updated_at = now
    db.add(session)

    audit = AuditLog(
        session_id=session_id,
        event_type="retry_parse",
        actor_id=x_user_id,
        actor_type="user",
        occurred_at=now,
        metadata_json=json.dumps({"contract_id": contract.id}),
    )
    db.add(audit)
    db.commit()

    # Re-trigger OCR
    from app.services.upload_service import _background_ocr

    asyncio.create_task(_background_ocr(session_id, contract.file_path, contract.file_type))

    return {"session_id": session_id, "state": "parsing", "message": "重新解析已启动"}


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
    audit = AuditLog(
        session_id=session_id,
        event_type="session_aborted",
        actor_id=x_user_id,
        actor_type="user",
        occurred_at=now,
        metadata_json=json.dumps({"reason": reason}),
    )
    db.add(audit)
    db.commit()

    await sse_manager.publish(
        session_id,
        "session_aborted",
        {"session_id": session_id, "reason": reason},
    )

    return {"session_id": session_id, "state": "aborted", "message": "审核已放弃"}
