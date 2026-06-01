import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.fields import verify_field
from app.database import Base
from app.models.contract import Contract
from app.models.extracted_field import ExtractedField
from app.models.session import ReviewSession
from app.schemas.field import FieldVerifyRequest


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _make_field(db, state="aborted"):
    contract = Contract(
        title="测试方案",
        original_filename="方案.pdf",
        file_type="pdf",
        file_path="/tmp/source.pdf",
        uploaded_by="tester",
    )
    db.add(contract)
    db.flush()
    session = ReviewSession(contract_id=contract.id, state=state, created_by="tester")
    db.add(session)
    db.flush()
    field = ExtractedField(
        session_id=session.id,
        field_name="project_name",
        field_value="原值",
        verification_status="unverified",
    )
    db.add(field)
    db.commit()
    return session, field


def test_verify_field_rejects_aborted_session_without_mutating_field():
    SessionLocal = _session_factory()
    db = SessionLocal()
    session, field = _make_field(db, state="aborted")

    with pytest.raises(HTTPException) as exc_info:
        verify_field(
            session.id,
            field.id,
            FieldVerifyRequest(verified_value="新值"),
            x_user_id="tester",
            db=db,
        )

    updated = db.query(ExtractedField).filter(ExtractedField.id == field.id).first()
    db.close()
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "SESSION_STATE_INVALID"
    assert updated.field_value == "原值"
    assert updated.verification_status == "unverified"


def test_verify_field_allows_scanning_session():
    SessionLocal = _session_factory()
    db = SessionLocal()
    session, field = _make_field(db, state="scanning")

    response = verify_field(
        session.id,
        field.id,
        FieldVerifyRequest(verified_value="新值"),
        x_user_id="tester",
        db=db,
    )

    updated = db.query(ExtractedField).filter(ExtractedField.id == field.id).first()
    db.close()
    assert response.verified_value == "新值"
    assert updated.field_value == "新值"
    assert updated.verification_status == "verified"
