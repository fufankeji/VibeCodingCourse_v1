"""Backfill a review session with water-review RAG issues.

Run from backend/ after DEEPSEEK_API_KEY and SILICONFLOW_API_KEY are available:

    uv run python scripts/backfill_water_rag_session.py 6f6410c8-e09d-439f-9ea8-fd73bd9e8049
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.extracted_field import ExtractedField
from app.models.session import ReviewSession
from app.services import water_review_service
from app.services.hitl_service import hitl_service
from app.services.ocr_service import STRUCTURED_FIELDS, _find_evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill a session with water-review RAG issues.")
    parser.add_argument("session_id")
    parser.add_argument("--file-path", default="", help="Optional source document path for PyMuPDF/DOCX fallback.")
    parser.add_argument("--artifact-dir", default="", help="Optional artifact directory.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = backfill_session(args.session_id, args.file_path, args.artifact_dir, db)
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


def backfill_session(session_id: str, file_path: str, artifact_dir: str, db: Any) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise SystemExit(f"ReviewSession not found: {session_id}")

    artifact_path = artifact_dir or str(Path("storage") / "contracts" / session.contract_id / "water_review")

    try:
        pipeline = water_review_service.run_pipeline(file_path, artifact_path, session_id)
    except Exception as exc:
        session.state = "aborted"
        session.updated_at = datetime.utcnow()
        db.add(
            AuditLog(
                session_id=session_id,
                event_type="system_failure",
                actor_id="system",
                actor_type="system",
                metadata_json=json.dumps(
                    {
                        "error": str(exc),
                        "error_code": "RAG_REVIEW_FAILED",
                        "node_name": "scripts.backfill_water_rag_session",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        raise

    _replace_fields(session_id, pipeline.get("fields", []), pipeline.get("full_text", ""), db)
    hitl_service._persist_review_items(session_id, pipeline.get("review_items", []), db)

    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if session:
        session.state = "hitl_pending"
        session.hitl_subtype = "interrupt"
        session.decided_high_risk = 0
        session.updated_at = datetime.utcnow()
        db.add(session)

    db.add(
        AuditLog(
            session_id=session_id,
            event_type="water_review_rag_backfilled",
            actor_id="system",
            actor_type="system",
            metadata_json=json.dumps(
                {
                    "artifact_dir": artifact_path,
                    "field_count": len(pipeline.get("fields", [])),
                    "rule_count": len(pipeline.get("rules", [])),
                    "item_count": len(pipeline.get("review_items", [])),
                    "vector_store": pipeline.get("rag", {}).get("index_manifest", {}).get("vector_store"),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()

    return {
        "session_id": session_id,
        "artifact_dir": artifact_path,
        "rule_count": len(pipeline.get("rules", [])),
        "item_count": len(pipeline.get("review_items", [])),
        "chunk_count": pipeline.get("rag", {}).get("index_manifest", {}).get("chunk_count"),
    }


def _replace_fields(session_id: str, extracted_fields: list[dict[str, Any]], full_text: str, db: Any) -> None:
    db.query(ExtractedField).filter(ExtractedField.session_id == session_id).delete()
    for data in extracted_fields:
        field_name = data.get("field_name", "")
        if field_name not in STRUCTURED_FIELDS:
            continue
        value = data.get("value", "")
        source_span = data.get("source_span") or {}
        confidence = int(data.get("confidence") or 50)
        db.add(
            ExtractedField(
                session_id=session_id,
                field_name=field_name,
                field_value=value,
                original_value=data.get("normalized_value") or value,
                confidence_score=confidence,
                needs_human_verification=confidence < 60,
                verification_status="unverified",
                source_evidence_text=_find_evidence(full_text, value),
                source_char_offset_start=source_span.get("char_start", 0),
                source_char_offset_end=source_span.get("char_end", 0),
            )
        )
    db.commit()


if __name__ == "__main__":
    main()
