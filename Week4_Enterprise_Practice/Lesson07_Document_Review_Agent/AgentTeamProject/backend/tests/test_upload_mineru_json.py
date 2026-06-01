import io
import json
import zipfile

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.contract import Contract
from app.models.document_parse_job import DocumentParseJob
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

    upload = UploadFile(filename="朝阳区百子湾职工住宅项目.json", file=io.BytesIO(_mineru_bytes()))
    db = TestingSessionLocal()
    try:
        response = await upload_service.handle_upload(upload, db, user_id="tester")
        contract = db.query(Contract).filter(Contract.id == response.contract_id).first()
        session = db.query(ReviewSession).filter(ReviewSession.id == response.session_id).first()
        job = db.query(DocumentParseJob).filter(DocumentParseJob.session_id == response.session_id).first()
    finally:
        db.close()

    assert response.file_type == "json"
    assert response.title == "朝阳区百子湾职工住宅项目"
    assert contract is not None
    assert contract.file_type == "json"
    assert contract.file_path.endswith("original.json")
    assert session is not None
    assert session.state == "parsing"
    assert job is not None
    assert job.status == "queued"
    assert job.provider == "mineru_json"
    assert job.source_file_type == "json"


@pytest.mark.asyncio
async def test_handle_upload_rejects_legacy_doc(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(upload_service.settings, "storage_path", str(tmp_path / "storage"))

    upload = UploadFile(
        filename="方案.doc",
        file=io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-word"),
    )
    db = TestingSessionLocal()
    try:
        with pytest.raises(Exception):
            await upload_service.handle_upload(upload, db, user_id="tester")
        assert db.query(Contract).count() == 0
        assert db.query(DocumentParseJob).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_handle_upload_rejects_fake_docx_zip(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(upload_service.settings, "storage_path", str(tmp_path / "storage"))

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("not-word.txt", "not a docx")
    upload = UploadFile(filename="方案.docx", file=io.BytesIO(payload.getvalue()))
    db = TestingSessionLocal()
    try:
        with pytest.raises(Exception):
            await upload_service.handle_upload(upload, db, user_id="tester")
        assert db.query(Contract).count() == 0
        assert db.query(DocumentParseJob).count() == 0
    finally:
        db.close()
