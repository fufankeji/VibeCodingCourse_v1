from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.audit_log import AuditLog
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.services.hitl_service import HITLService


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_persist_review_items_pushes_real_scan_progress_summary(monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    session = ReviewSession(contract_id="contract-1", state="scanning", created_by="tester")
    db.add(session)
    db.commit()
    service = HITLService()
    pushed: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        service,
        "_push_sse_event",
        lambda session_id, event_type, data: pushed.append((session_id, event_type, data)),
    )

    service._persist_review_items(
        session.id,
        [
            {"id": "item-1", "risk_level": "HIGH", "risk_category": "章节与材料完整性"},
            {"id": "item-2", "risk_level": "MEDIUM", "risk_category": "章节与材料完整性"},
            {"id": "item-3", "risk_level": "LOW", "risk_category": "土石方平衡"},
        ],
        db,
    )

    persisted_count = db.query(ReviewItem).filter(ReviewItem.session_id == session.id).count()
    updated_session = db.query(ReviewSession).filter(ReviewSession.id == session.id).first()
    db.close()
    assert persisted_count == 3
    assert updated_session.total_high_risk == 1
    assert updated_session.total_medium_risk == 1
    assert updated_session.total_low_risk == 1
    assert pushed == [
        (
            session.id,
            "scan_progress",
            {
                "found_count": 3,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 1,
                "category_counts": {"章节与材料完整性": 2, "土石方平衡": 1},
            },
        )
    ]


def test_workflow_thread_failure_reverts_scanning_session_to_parsed(monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    session = ReviewSession(contract_id="contract-1", state="scanning", created_by="tester")
    db.add(session)
    db.commit()
    session_id = session.id
    db.close()

    def fail_workflow(**_kwargs):
        raise RuntimeError("workflow exploded")

    monkeypatch.setattr("app.workflow.graph.run_workflow_sync", fail_workflow)
    monkeypatch.setattr("app.services.hitl_service.SessionLocal", SessionLocal)
    service = HITLService()
    pushed: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        service,
        "_push_sse_event",
        lambda session_id, event_type, data: pushed.append((session_id, event_type, data)),
    )

    service._run_workflow_thread(
        session_id=session_id,
        contract_id=session_id,
        thread_id="thread-1",
        full_text="text",
        precomputed_review_items=[],
    )

    db = SessionLocal()
    try:
        updated = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.session_id == session_id, AuditLog.event_type == "system_failure")
            .first()
        )
        assert updated.state == "parsed"
        assert audit is not None
        assert "workflow exploded" in audit.metadata_json
        assert ("system_failure", "WORKFLOW_ERROR") in [
            (event_type, data.get("error_code")) for _, event_type, data in pushed
        ]
        assert ("state_changed", "parsed") in [
            (event_type, data.get("state")) for _, event_type, data in pushed
        ]
    finally:
        db.close()
