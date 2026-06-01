from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite only
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import audit_log, contract, document_parse_job, extracted_field, report, review_item, session  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_document_parse_job_columns()


def _ensure_document_parse_job_columns():
    inspector = inspect(engine)
    if "document_parse_jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("document_parse_jobs")}
    additions = {
        "started_at": "DATETIME",
        "completed_at": "DATETIME",
        "timing_json": "TEXT",
    }
    with engine.begin() as conn:
        for name, column_type in additions.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE document_parse_jobs ADD COLUMN {name} {column_type}"))
