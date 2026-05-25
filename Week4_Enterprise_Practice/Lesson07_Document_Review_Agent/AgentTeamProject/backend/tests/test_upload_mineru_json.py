import asyncio
import io
import json

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.services import upload_service


def _mineru_bytes() -> bytes:
    return json.dumps(
        {
            "pdf_info": [
                {
                    "page_idx": 0,
                    "para_blocks": [
                        {
                            "bbox": [10, 20, 120, 40],
                            "type": "title",
                            "index": 1,
                            "lines": [{"spans": [{"content": "朝阳区百子湾职工住宅项目"}]}],
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_handle_upload_accepts_mineru_json(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(upload_service.settings, "storage_path", str(tmp_path / "storage"))

    async def noop_background_ocr(session_id: str, file_path: str, file_type: str) -> None:
        return None

    created_tasks = []
    monkeypatch.setattr(upload_service, "_background_ocr", noop_background_ocr)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: created_tasks.append(coro))

    upload = UploadFile(filename="朝阳区百子湾职工住宅项目.json", file=io.BytesIO(_mineru_bytes()))
    db = TestingSessionLocal()
    try:
        response = await upload_service.handle_upload(upload, db, user_id="tester")
        contract = db.query(Contract).filter(Contract.id == response.contract_id).first()
        session = db.query(ReviewSession).filter(ReviewSession.id == response.session_id).first()
    finally:
        for coro in created_tasks:
            coro.close()
        db.close()

    assert response.file_type == "json"
    assert response.title == "朝阳区百子湾职工住宅项目"
    assert contract is not None
    assert contract.file_type == "json"
    assert contract.file_path.endswith("original.json")
    assert session is not None
    assert session.state == "parsing"
