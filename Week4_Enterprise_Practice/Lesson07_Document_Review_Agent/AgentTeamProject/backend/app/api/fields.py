import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.extracted_field import ExtractedField
from app.models.session import ReviewSession
from app.schemas.field import (
    ExtractedFieldResponse,
    FieldListResponse,
    FieldVerifyRequest,
    FieldVerifyResponse,
)

router = APIRouter()

FIELD_VERIFY_ACTIVE_STATES = {"scanning", "hitl_field_verify"}


@router.get("/{session_id}/fields", response_model=FieldListResponse)
def list_fields(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")

    fields = db.query(ExtractedField).filter(ExtractedField.session_id == session_id).all()
    return FieldListResponse(
        items=[ExtractedFieldResponse.model_validate(f) for f in fields],
        total=len(fields),
    )


@router.patch("/{session_id}/fields/{field_id}", response_model=FieldVerifyResponse)
def verify_field(
    session_id: str,
    field_id: str,
    body: FieldVerifyRequest,
    x_user_id: str = Header(default="anonymous", alias="X-User-ID"),
    db: Session = Depends(get_db),
):
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")
    if session.state not in FIELD_VERIFY_ACTIVE_STATES:
        raise APIError.session_state_invalid(session.state, "scanning/hitl_field_verify")

    field = db.query(ExtractedField).filter(
        ExtractedField.id == field_id, ExtractedField.session_id == session_id
    ).first()
    if not field:
        raise APIError.not_found("ExtractedField")

    now = datetime.utcnow()
    field.verified_value = body.verified_value
    field.field_value = body.verified_value
    field.verification_status = "verified"
    field.verified_by = x_user_id
    field.verified_at = now
    db.add(field)

    audit = AuditLog(
        session_id=session_id,
        event_type="field_verified",
        actor_id=x_user_id,
        actor_type="user",
        occurred_at=now,
        metadata_json=json.dumps(
            {
                "field_id": field_id,
                "field_name": field.field_name,
                "verified_value": body.verified_value,
            }
        ),
    )
    db.add(audit)
    db.commit()

    return FieldVerifyResponse(
        id=field.id,
        field_name=field.field_name,
        verified_value=body.verified_value,
        verification_status="verified",
        verified_by=x_user_id,
        verified_at=now,
        message="字段核验成功",
    )
