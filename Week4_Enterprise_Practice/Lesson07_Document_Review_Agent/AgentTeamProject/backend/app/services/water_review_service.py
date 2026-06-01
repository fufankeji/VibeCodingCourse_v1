"""Water-soil conservation review pipeline façade.

Implementation is split by responsibility across:
- water_review_models: shared dataclasses and constants
- water_review_parsers: MinerU/Markdown/PDF/DOCX parsing
- water_review_chunking: semantic/window/table-row chunking
- water_review_extraction: deterministic field extraction
- water_review_reviewing: rule issue assembly

This module intentionally preserves the historical import surface used by API
handlers and tests.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.mineru_table_fact_service import extract_table_facts
from app.services.review_rule_schema import build_review_rule_topics, normalize_review_rules
from app.services.water_review_chunking import build_chunks
from app.services.water_review_extraction import extract_fields
from app.services.water_review_models import (
    DATA_DIR,
    DEFAULT_MINERU_JSON as _DEFAULT_MINERU_JSON,
    DEFAULT_MINERU_MD as _DEFAULT_MINERU_MD,
    DEFAULT_RULE_SET,
    QUICK_VALIDATION_ISSUE_COUNT,
    RULES,
    SECTION_KEYWORDS,
    WATER_FIELDS,
    ParsedBlock,
    ReviewChunk,
)
from app.services.water_review_parsers import (
    _parse_docx,
    _parse_markdown,
    _parse_mineru_json,
    _parse_pdf,
    _section_path,
    _update_section_stack,
)
from app.services import water_review_parsers as _parsers
from app.services.water_review_reviewing import _issues_from_configured_rules, review_rules
from app.services.water_review_utils import _write_json

DEFAULT_MINERU_JSON = _DEFAULT_MINERU_JSON
DEFAULT_MINERU_MD = _DEFAULT_MINERU_MD
logger = logging.getLogger(__name__)


def run_pipeline(file_path: str, artifact_dir: str, session_id: str) -> dict[str, Any]:
    """Parse, chunk, extract fields, review rules, and persist JSON artifacts."""
    total_started = time.perf_counter()
    timings: dict[str, int] = {}
    logger.info(
        "water_review_run_pipeline_start session_id=%s file_path=%s artifact_dir=%s langextract_enabled=%s",
        session_id,
        file_path,
        artifact_dir,
        settings.langextract_enabled,
    )
    started = time.perf_counter()
    blocks = parse_document(file_path)
    timings["pipeline_parse_document_duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info(
        "water_review_parse_done session_id=%s block_count=%s duration_ms=%s",
        session_id,
        len(blocks),
        timings["pipeline_parse_document_duration_ms"],
    )
    started = time.perf_counter()
    chunks = build_chunks(blocks)
    timings["pipeline_chunk_duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info(
        "water_review_chunk_done session_id=%s chunk_count=%s duration_ms=%s",
        session_id,
        len(chunks),
        timings["pipeline_chunk_duration_ms"],
    )
    started = time.perf_counter()
    fallback_fields = extract_fields(chunks)
    timings["pipeline_field_extract_duration_ms"] = int((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    table_facts = extract_table_facts(blocks, chunks)
    timings["pipeline_table_fact_duration_ms"] = int((time.perf_counter() - started) * 1000)
    langextract_facts: list[dict[str, Any]] = list(table_facts)
    cross_chapter_findings: list[dict[str, Any]] = []
    if settings.langextract_enabled:
        from app.services.langextract_service import (
            build_cross_chapter_findings,
            build_fact_index,
            facts_to_extracted_fields,
            run_langextract,
        )

        started = time.perf_counter()
        langextract_facts = [*table_facts, *run_langextract(chunks)]
        timings["pipeline_langextract_duration_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "water_review_langextract_done session_id=%s table_fact_count=%s total_fact_count=%s duration_ms=%s",
            session_id,
            len(table_facts),
            len(langextract_facts),
            timings["pipeline_langextract_duration_ms"],
        )
        fields = facts_to_extracted_fields(langextract_facts, fallback_fields)
        fact_index = build_fact_index(langextract_facts)
        cross_chapter_findings = build_cross_chapter_findings(langextract_facts)
    else:
        if table_facts:
            from app.services.langextract_service import build_fact_index, facts_to_extracted_fields

            fields = facts_to_extracted_fields(table_facts, fallback_fields)
            fact_index = build_fact_index(table_facts)
        else:
            fields = fallback_fields
            fact_index = {"fact_count": 0, "fields": [], "by_field": {}}
    rules = load_rule_set()

    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)
    from app.services.rag_service import run_rag_review

    started = time.perf_counter()
    rag_result = run_rag_review(
        session_id,
        chunks,
        rules,
        artifact_path,
        facts=langextract_facts,
        findings=cross_chapter_findings,
    )
    timings["pipeline_rag_duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info(
        "water_review_rag_done session_id=%s issue_count=%s duration_ms=%s",
        session_id,
        len(rag_result.get("issues") or []),
        timings["pipeline_rag_duration_ms"],
    )
    from app.services.review_config_service import list_check_item_specs

    started = time.perf_counter()
    configured_check_items = [item for item in list_check_item_specs() if item.get("enabled") is not False]
    configured_issues = _issues_from_configured_rules(
        session_id,
        chunks,
        "\n".join(chunk.text for chunk in chunks),
        fields,
        configured_check_items,
        limit=len(configured_check_items),
        evidence_store=_pipeline_evidence_store(session_id, rag_result) if configured_check_items else None,
    )
    timings["pipeline_configured_review_duration_ms"] = int((time.perf_counter() - started) * 1000)
    issues = [*rag_result["issues"], *configured_issues]
    rule_topics = build_review_rule_topics(rules, issues, configured_check_items=configured_check_items)
    started = time.perf_counter()
    _write_json(artifact_path / "parsed_blocks.json", [asdict(b) for b in blocks])
    _write_json(artifact_path / "review_chunks.json", [asdict(c) for c in chunks])
    _write_json(artifact_path / "extracted_fields.json", fields)
    _write_json(artifact_path / "langextract_facts.json", langextract_facts)
    _write_json(artifact_path / "langextract_fact_index.json", fact_index)
    _write_json(artifact_path / "cross_chapter_findings.json", cross_chapter_findings)
    _write_json(artifact_path / "review_rule_topics.json", rule_topics)
    _write_json(artifact_path / "issues.json", issues)
    timings["pipeline_artifact_write_duration_ms"] = int((time.perf_counter() - started) * 1000)
    timings["pipeline_total_duration_ms"] = int((time.perf_counter() - total_started) * 1000)
    logger.info(
        "water_review_run_pipeline_done session_id=%s block_count=%s chunk_count=%s field_count=%s issue_count=%s "
        "artifact_dir=%s duration_ms=%s",
        session_id,
        len(blocks),
        len(chunks),
        len(fields),
        len(issues),
        artifact_path,
        timings["pipeline_total_duration_ms"],
    )

    return {
        "full_text": "\n".join(block.text for block in blocks),
        "blocks": blocks,
        "chunks": chunks,
        "fields": fields,
        "facts": langextract_facts,
        "cross_chapter_findings": cross_chapter_findings,
        "review_items": issues,
        "rules": rules,
        "rule_topics": rule_topics,
        "rag": rag_result,
        "artifact_dir": str(artifact_path),
        "timings": timings,
    }


def _pipeline_evidence_store(session_id: str, rag_result: dict[str, Any]) -> Any | None:
    manifest = rag_result.get("index_manifest") if isinstance(rag_result, dict) else {}
    if not isinstance(manifest, dict):
        return None
    vector_store = str(manifest.get("vector_store") or "").strip()
    if not vector_store:
        return None
    try:
        from app.services.rag_service import ChromaChunkStore, SiliconFlowEmbeddingProvider

        return ChromaChunkStore(Path(vector_store), session_id, SiliconFlowEmbeddingProvider())
    except Exception:
        return None


def parse_document(file_path: str | None = None) -> list[ParsedBlock]:
    """Load an explicit source first, then fall back to bundled MinerU samples."""
    _parsers.DEFAULT_MINERU_JSON = DEFAULT_MINERU_JSON
    _parsers.DEFAULT_MINERU_MD = DEFAULT_MINERU_MD
    return _parsers.parse_document(file_path)


def load_rule_set(path: Path = DEFAULT_RULE_SET) -> list[dict[str, Any]]:
    if not path.exists():
        return normalize_review_rules(RULES)
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", []) if isinstance(data, dict) else data
    return normalize_review_rules(rules or RULES)
