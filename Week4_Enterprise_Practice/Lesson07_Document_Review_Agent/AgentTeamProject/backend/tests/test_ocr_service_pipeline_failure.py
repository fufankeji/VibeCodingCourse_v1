import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.session import ReviewSession
from app.services import ocr_service, water_review_service


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.mark.asyncio
async def test_extract_fields_pipeline_failure_preserves_parsed_session(monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        session = ReviewSession(contract_id="contract-1", state="parsed", created_by="tester")
        db.add(session)
        db.commit()

        def fake_run_pipeline(file_path, artifact_dir, session_id):
            raise RuntimeError("vector store failed")

        monkeypatch.setattr(water_review_service, "run_pipeline", fake_run_pipeline)

        result = await ocr_service.extract_fields(session.id, "", db, file_path="/tmp/parsed.json")

        updated_session = db.query(ReviewSession).filter(ReviewSession.id == session.id).first()
        assert result is None
        assert updated_session.state == "parsed"
    finally:
        db.close()
