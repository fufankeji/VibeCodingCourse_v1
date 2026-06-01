import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.sessions import abort_session
from app.core.sse import sse_manager
from app.database import Base
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.schemas.session import AbortRequest


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.mark.asyncio
async def test_abort_session_publishes_session_aborted_and_state_changed(tmp_path):
    SessionLocal = _session_factory()
    db = SessionLocal()
    source = tmp_path / "方案.pdf"
    source.write_bytes(b"%PDF- fake")
    contract = Contract(
        title="测试方案",
        original_filename=source.name,
        file_type="pdf",
        file_path=str(source),
        uploaded_by="tester",
    )
    db.add(contract)
    db.flush()
    session = ReviewSession(contract_id=contract.id, state="parsing", created_by="tester")
    db.add(session)
    db.commit()
    session_id = session.id
    queue = asyncio.Queue()
    sse_manager._queues[session_id] = [queue]

    try:
        await abort_session(session_id, AbortRequest(reason="测试中止"), x_user_id="tester", db=db)
        first = queue.get_nowait()
        second = queue.get_nowait()
    finally:
        sse_manager._queues.pop(session_id, None)
        db.close()

    assert first["event"] == "session_aborted"
    assert json.loads(first["data"])["reason"] == "测试中止"
    assert second["event"] == "state_changed"
    assert json.loads(second["data"])["state"] == "aborted"
