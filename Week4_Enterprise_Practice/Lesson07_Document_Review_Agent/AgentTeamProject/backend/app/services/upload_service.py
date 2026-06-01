import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import APIError
from app.models.audit_log import AuditLog
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.schemas.contract import UploadResponse
from app.services.document_parse_worker import create_parse_job

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


def _detect_file_type(header: bytes, filename: str | None = None) -> str | None:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".doc":
        return None
    if header[:5] == PDF_MAGIC:
        return "pdf"
    if header[:4] == ZIP_MAGIC:
        return "docx"
    if header.lstrip().startswith((b"{", b"[")):
        return "json"
    if suffix == ".json":
        return "json"
    return None


def _check_pdf_integrity(file_path: str) -> tuple[bool, bool]:
    """Returns (is_valid, is_encrypted)."""
    try:
        import PyPDF2

        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            if reader.is_encrypted:
                return True, True
            _ = len(reader.pages)
        return True, False
    except Exception:
        return False, False


def _check_docx_integrity(file_path: str) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return False
            zf.testzip()
        return True
    except Exception:
        return False


def _check_mineru_json_integrity(file_path: str) -> bool:
    try:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    pages = data.get("pdf_info")
    if not isinstance(pages, list) or not pages:
        return False
    return any(isinstance(page, dict) and page.get("para_blocks") for page in pages)


def _is_scanned_pdf(file_path: str) -> bool:
    """Heuristic: if text extraction yields very little text, treat as scanned."""
    try:
        import PyPDF2

        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            total_text = ""
            for page in reader.pages[:3]:  # check first 3 pages
                total_text += page.extract_text() or ""
        return len(total_text.strip()) < 50
    except Exception:
        return False


def _find_reusable_contract(db: Session, *, file_type: str, content: bytes, user_id: str) -> tuple[Contract, ReviewSession] | None:
    candidates = (
        db.query(Contract)
        .filter(
            Contract.file_type == file_type,
            Contract.uploaded_by == user_id,
            Contract.contract_status != "aborted",
        )
        .order_by(Contract.created_at.desc())
        .all()
    )
    for contract in candidates:
        path = Path(contract.file_path)
        if not path.exists():
            continue
        try:
            if path.read_bytes() != content:
                continue
        except OSError:
            continue
        session = (
            db.query(ReviewSession)
            .filter(ReviewSession.contract_id == contract.id, ReviewSession.state != "aborted")
            .order_by(ReviewSession.created_at.desc())
            .first()
        )
        if session:
            return contract, session
    return None


async def handle_upload(
    file: UploadFile,
    db: Session,
    user_id: str = "anonymous",
    contract_title: str | None = None,
) -> UploadResponse:
    # Read header for magic bytes check
    header = await file.read(8)
    file_type = _detect_file_type(header, file.filename)
    if file_type is None:
        raise APIError.unsupported_file_type()

    # Read remaining content
    rest = await file.read()
    content = header + rest

    # File size check
    if len(content) > MAX_FILE_SIZE:
        raise APIError.file_too_large(50)

    reusable = _find_reusable_contract(db, file_type=file_type, content=content, user_id=user_id)
    if reusable:
        contract, session = reusable
        return UploadResponse(
            contract_id=contract.id,
            session_id=session.id,
            title=contract.title,
            file_type=contract.file_type,
            is_scanned_document=contract.is_scanned_document,
            state=session.state,
            message="文件已存在，已复用已有解析任务",
        )

    # Persist to temp location first
    contract_id = str(uuid.uuid4())
    storage_dir = Path(settings.storage_path) / "contracts" / contract_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    original_filename = file.filename or f"contract.{file_type}"
    safe_filename = f"original.{file_type}"
    file_path = str(storage_dir / safe_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Integrity check
    is_encrypted = False
    is_scanned = False
    if file_type == "pdf":
        valid, is_encrypted = _check_pdf_integrity(file_path)
        if not valid:
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise APIError.corrupt_file()
        if is_encrypted:
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise APIError.encrypted_pdf()
        is_scanned = _is_scanned_pdf(file_path)
    elif file_type == "docx":
        if not _check_docx_integrity(file_path):
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise APIError.corrupt_file()
    elif file_type == "json":
        if not _check_mineru_json_integrity(file_path):
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise APIError.corrupt_file()

    # Derive title from filename
    title = (contract_title or "").strip() or Path(original_filename).stem

    # Create DB records in a transaction
    contract = Contract(
        id=contract_id,
        title=title,
        original_filename=original_filename,
        file_type=file_type,
        contract_status="processing",
        is_scanned_document=is_scanned,
        file_path=file_path,
        uploaded_by=user_id,
        uploaded_at=datetime.utcnow(),
    )
    db.add(contract)

    session = ReviewSession(
        contract_id=contract_id,
        state="parsing",
        is_scanned_document=is_scanned,
        created_by=user_id,
    )
    db.add(session)
    db.flush()  # populate session.id
    job = create_parse_job(
        db,
        session_id=session.id,
        contract_id=contract_id,
        source_file_path=file_path,
        source_file_type=file_type,
    )
    db.flush()

    audit = AuditLog(
        session_id=session.id,
        event_type="contract_uploaded",
        actor_id=user_id,
        actor_type="user",
        metadata_json=json.dumps(
            {
                "contract_id": contract_id,
                "original_filename": original_filename,
                "file_type": file_type,
                "file_size_bytes": len(content),
                "parse_job_id": job.id,
            }
        ),
    )
    db.add(audit)
    db.commit()
    db.refresh(session)

    return UploadResponse(
        contract_id=contract_id,
        session_id=session.id,
        title=title,
        file_type=file_type,
        is_scanned_document=is_scanned,
        state="parsing",
        message="文件上传成功，正在解析中",
    )
