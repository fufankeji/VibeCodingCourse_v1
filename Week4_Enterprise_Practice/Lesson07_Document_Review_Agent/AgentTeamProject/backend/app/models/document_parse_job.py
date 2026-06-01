import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentParseJob(Base):
    __tablename__ = "document_parse_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    contract_id: Mapped[str] = mapped_column(String(36), index=True)
    source_file_path: Mapped[str] = mapped_column(String(500))
    source_file_type: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mineru_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mineru_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_zip_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_json_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_markdown_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
