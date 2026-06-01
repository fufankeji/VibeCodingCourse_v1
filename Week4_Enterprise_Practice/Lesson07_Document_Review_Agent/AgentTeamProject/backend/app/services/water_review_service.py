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
from dataclasses import asdict, fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.core_extraction_service import build_core_extraction_chunks
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

PIPELINE_STAGE_DEFS: tuple[dict[str, str], ...] = (
    {"id": "parsed_blocks", "title": "读取 MinerU 结构化解析结果", "artifact": "parsed_blocks.json"},
    {"id": "review_chunks", "title": "构建审查文本块", "artifact": "review_chunks.json"},
    {"id": "extracted_fields", "title": "字段抽取", "artifact": "extracted_fields.json"},
    {"id": "langextract_facts", "title": "LangExtract 证据事实", "artifact": "langextract_facts.json"},
    {"id": "rag_index", "title": "向量索引", "artifact": "rag_index_manifest.json"},
    {"id": "rag_retrievals", "title": "RAG 证据召回", "artifact": "rag_retrievals.json"},
    {"id": "rag_issues", "title": "规则模型判定", "artifact": "rag_issues.json"},
    {"id": "configured_review", "title": "配置化规则复核", "artifact": "review_rule_topics.json"},
    {"id": "review_artifacts", "title": "审查结果落盘", "artifact": "issues.json"},
    {"id": "review_items_db", "title": "写入审查任务", "artifact": ""},
)


def run_pipeline(file_path: str, artifact_dir: str, session_id: str) -> dict[str, Any]:
    """Parse, chunk, extract fields, review rules, and persist JSON artifacts."""
    total_started = time.perf_counter()
    timings: dict[str, int] = {}
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)
    source_signature = _source_signature(file_path)
    cache_source_matches = _cache_source_matches(artifact_path, source_signature)
    if not cache_source_matches:
        _clear_pipeline_cache(artifact_path)
    stage_statuses = _base_pipeline_stages()
    cache_hits: dict[str, bool] = {
        "parsed_blocks": False,
        "review_chunks": False,
        "prerag_artifacts": False,
        "rag_retrievals": False,
        "rag_issues": False,
    }
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
    logger.info(
        "water_review_run_pipeline_start session_id=%s file_path=%s artifact_dir=%s "
        "langextract_enabled=%s langextract_main_pipeline_enabled=%s",
        session_id,
        file_path,
        artifact_dir,
        settings.langextract_enabled,
        settings.langextract_main_pipeline_enabled,
    )
    started = time.perf_counter()
    cached_blocks = _load_cached_dataclass_list(artifact_path / "parsed_blocks.json", ParsedBlock) if cache_source_matches else None
    if cached_blocks is not None:
        blocks = cached_blocks
        cache_hits["parsed_blocks"] = True
        timings["pipeline_parse_document_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _set_stage(
            stage_statuses,
            "parsed_blocks",
            "cached",
            item_count=len(blocks),
            duration_ms=timings["pipeline_parse_document_duration_ms"],
        )
    else:
        _set_stage(stage_statuses, "parsed_blocks", "running")
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
        blocks = parse_document(file_path)
        timings["pipeline_parse_document_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _write_json(artifact_path / "parsed_blocks.json", [asdict(b) for b in blocks])
        _set_stage(
            stage_statuses,
            "parsed_blocks",
            "completed",
            item_count=len(blocks),
            duration_ms=timings["pipeline_parse_document_duration_ms"],
        )
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
    timings["pipeline_parse_document_duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info(
        "water_review_parse_done session_id=%s block_count=%s duration_ms=%s",
        session_id,
        len(blocks),
        timings["pipeline_parse_document_duration_ms"],
    )
    started = time.perf_counter()
    cached_chunks = _load_cached_dataclass_list(artifact_path / "review_chunks.json", ReviewChunk) if cache_source_matches else None
    if cached_chunks is not None:
        chunks = cached_chunks
        cache_hits["review_chunks"] = True
        timings["pipeline_chunk_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _set_stage(
            stage_statuses,
            "review_chunks",
            "cached",
            item_count=len(chunks),
            duration_ms=timings["pipeline_chunk_duration_ms"],
        )
    else:
        _set_stage(stage_statuses, "review_chunks", "running")
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
        chunks = build_chunks(blocks)
        timings["pipeline_chunk_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _write_json(artifact_path / "review_chunks.json", [asdict(c) for c in chunks])
        _set_stage(
            stage_statuses,
            "review_chunks",
            "completed",
            item_count=len(chunks),
            duration_ms=timings["pipeline_chunk_duration_ms"],
        )
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
    timings["pipeline_chunk_duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info(
        "water_review_chunk_done session_id=%s chunk_count=%s duration_ms=%s",
        session_id,
        len(chunks),
        timings["pipeline_chunk_duration_ms"],
    )
    core_selection = build_core_extraction_chunks(chunks, session_id, artifact_path)
    core_chunks = core_selection.chunks
    logger.info(
        "water_review_core_extraction_chunks_selected session_id=%s mode=%s selected_count=%s input_count=%s",
        session_id,
        core_selection.mode,
        core_selection.trace.get("selected_count"),
        core_selection.trace.get("input_count"),
    )
    cached_prerag = _load_cached_prerag_artifacts(artifact_path) if cache_source_matches else None
    if cached_prerag is not None:
        fields, langextract_facts, fact_index, cross_chapter_findings = cached_prerag
        cache_hits["prerag_artifacts"] = True
        _set_stage(stage_statuses, "extracted_fields", "cached", item_count=len(fields), duration_ms=0)
        _set_stage(stage_statuses, "langextract_facts", "cached", item_count=len(langextract_facts), duration_ms=0)
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
    else:
        _set_stage(stage_statuses, "extracted_fields", "running")
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
        started = time.perf_counter()
        fallback_fields = extract_fields(core_chunks)
        timings["pipeline_field_extract_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _set_stage(
            stage_statuses,
            "extracted_fields",
            "completed",
            item_count=len(fallback_fields),
            duration_ms=timings["pipeline_field_extract_duration_ms"],
        )
        started = time.perf_counter()
        table_facts = extract_table_facts(blocks, chunks)
        timings["pipeline_table_fact_duration_ms"] = int((time.perf_counter() - started) * 1000)
        langextract_facts: list[dict[str, Any]] = list(table_facts)
        langextract_failed = ""
        cross_chapter_findings: list[dict[str, Any]] = []
        _set_stage(stage_statuses, "langextract_facts", "running", item_count=len(table_facts))
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
        run_sync_langextract = settings.langextract_enabled and settings.langextract_main_pipeline_enabled
        if run_sync_langextract:
            from app.services.langextract_service import (
                LangExtractReviewError,
                build_cross_chapter_findings,
                build_fact_index,
                facts_to_extracted_fields,
                run_langextract,
            )

            started = time.perf_counter()
            try:
                langextract_facts = [*table_facts, *run_langextract(core_chunks)]
                langextract_failed = ""
            except LangExtractReviewError as exc:
                langextract_failed = str(exc)
                langextract_facts = list(table_facts)
                logger.warning(
                    "water_review_langextract_degraded session_id=%s table_fact_count=%s error=%s",
                    session_id,
                    len(table_facts),
                    exc,
                )
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
            langextract_failed = "已跳过同步 LangExtract 证据增强，主流程使用 MinerU 表格事实和规则字段继续审查。"
            if table_facts:
                from app.services.langextract_service import build_fact_index, facts_to_extracted_fields

                fields = facts_to_extracted_fields(table_facts, fallback_fields)
                fact_index = build_fact_index(table_facts)
            else:
                fields = fallback_fields
                fact_index = {"fact_count": 0, "fields": [], "by_field": {}}
        started = time.perf_counter()
        _write_json(artifact_path / "extracted_fields.json", fields)
        _write_json(artifact_path / "langextract_facts.json", langextract_facts)
        _write_json(artifact_path / "langextract_fact_index.json", fact_index)
        _write_json(artifact_path / "cross_chapter_findings.json", cross_chapter_findings)
        timings["pipeline_prerag_artifact_write_duration_ms"] = int((time.perf_counter() - started) * 1000)
        _set_stage(stage_statuses, "extracted_fields", "completed", item_count=len(fields))
        if run_sync_langextract and langextract_failed:
            langextract_status = "degraded"
        elif run_sync_langextract:
            langextract_status = "completed"
        else:
            langextract_status = "skipped"
        _set_stage(
            stage_statuses,
            "langextract_facts",
            langextract_status,
            item_count=len(langextract_facts),
            duration_ms=timings.get("pipeline_langextract_duration_ms", 0),
            message=langextract_failed,
        )
        _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)

    rules = load_rule_set()

    from app.services.rag_service import run_rag_review

    _set_stage(stage_statuses, "rag_index", "running")
    _set_stage(stage_statuses, "rag_retrievals", "pending")
    _set_stage(stage_statuses, "rag_issues", "pending")
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
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
    rag_cache_hits = rag_result.get("cache_hits") if isinstance(rag_result, dict) else {}
    if isinstance(rag_cache_hits, dict):
        cache_hits["rag_retrievals"] = bool(rag_cache_hits.get("rag_retrievals"))
        cache_hits["rag_issues"] = bool(rag_cache_hits.get("rag_issues"))
    _set_stage(
        stage_statuses,
        "rag_index",
        "cached" if cache_hits["rag_retrievals"] else "completed",
        item_count=len(chunks),
        duration_ms=timings["pipeline_rag_duration_ms"],
    )
    _set_stage(
        stage_statuses,
        "rag_retrievals",
        "cached" if cache_hits["rag_retrievals"] else "completed",
        item_count=len(rag_result.get("retrievals") or []),
        duration_ms=timings["pipeline_rag_duration_ms"],
    )
    _set_stage(
        stage_statuses,
        "rag_issues",
        "cached" if cache_hits["rag_issues"] else "completed",
        item_count=len(rag_result.get("issues") or []),
        duration_ms=timings["pipeline_rag_duration_ms"],
    )
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
    logger.info(
        "water_review_rag_done session_id=%s issue_count=%s duration_ms=%s",
        session_id,
        len(rag_result.get("issues") or []),
        timings["pipeline_rag_duration_ms"],
    )
    from app.services.review_config_service import list_check_item_specs

    _set_stage(stage_statuses, "configured_review", "running")
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
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
    _set_stage(
        stage_statuses,
        "configured_review",
        "completed",
        item_count=len(configured_issues),
        duration_ms=timings["pipeline_configured_review_duration_ms"],
    )
    issues = [*rag_result["issues"], *configured_issues]
    rule_topics = build_review_rule_topics(rules, issues, configured_check_items=configured_check_items)
    _set_stage(stage_statuses, "review_artifacts", "running")
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
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
    _set_stage(
        stage_statuses,
        "review_artifacts",
        "completed",
        item_count=len(issues),
        duration_ms=timings["pipeline_artifact_write_duration_ms"],
    )
    _write_pipeline_status(artifact_path, session_id, stage_statuses, timings, cache_hits, source_signature)
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
        "cache_hits": cache_hits,
    }


def build_pipeline_status(session_id: str, artifact_dir: str | Path | None, review_item_count: int | None = None) -> dict[str, Any]:
    artifact_path = Path(artifact_dir).resolve() if artifact_dir else None
    stages = _base_pipeline_stages()
    timings: dict[str, Any] = {}
    cache_hits: dict[str, Any] = {}
    source_signature: dict[str, Any] = {}
    updated_at = ""
    if artifact_path:
        status_path = artifact_path / "pipeline_status.json"
        persisted = _read_json_object(status_path)
        if persisted:
            timings = persisted.get("timings") if isinstance(persisted.get("timings"), dict) else {}
            cache_hits = persisted.get("cache_hits") if isinstance(persisted.get("cache_hits"), dict) else {}
            source_signature = persisted.get("source_signature") if isinstance(persisted.get("source_signature"), dict) else {}
            updated_at = str(persisted.get("updated_at") or "")
            persisted_by_id = {
                str(stage.get("id")): stage
                for stage in persisted.get("stages", [])
                if isinstance(stage, dict) and stage.get("id")
            }
            for stage in stages:
                saved = persisted_by_id.get(stage["id"])
                if saved:
                    stage.update({key: value for key, value in saved.items() if key in stage})
        for stage in stages:
            artifact = str(stage.get("artifact") or "")
            if not artifact or not artifact_path:
                continue
            target = artifact_path / artifact
            if not target.exists():
                continue
            if stage["status"] in {"pending", "not_started"}:
                stage["status"] = "completed"
            stage["artifact_exists"] = True
            if stage["id"] in {"parsed_blocks", "review_chunks", "extracted_fields", "langextract_facts"}:
                stage["cache_reusable"] = True
            if stage.get("item_count") is None:
                stage["item_count"] = _json_artifact_count(target)
        if review_item_count is not None:
            _set_stage(stages, "review_items_db", "completed" if review_item_count > 0 else "pending", item_count=review_item_count)
    return {
        "session_id": session_id,
        "available": bool(artifact_path and artifact_path.exists()),
        "artifact_dir": str(artifact_path) if artifact_path else "",
        "updated_at": updated_at,
        "stages": stages,
        "timings": timings,
        "cache_hits": cache_hits,
        "source_signature": source_signature,
    }


def _base_pipeline_stages() -> list[dict[str, Any]]:
    return [
        {
            "id": stage["id"],
            "title": stage["title"],
            "artifact": stage["artifact"],
            "status": "pending",
            "cache_reusable": False,
            "artifact_exists": False,
            "item_count": None,
            "duration_ms": None,
            "message": "",
        }
        for stage in PIPELINE_STAGE_DEFS
    ]


def _set_stage(
    stages: list[dict[str, Any]],
    stage_id: str,
    status: str,
    *,
    item_count: int | None = None,
    duration_ms: int | None = None,
    message: str = "",
) -> None:
    for stage in stages:
        if stage.get("id") != stage_id:
            continue
        stage["status"] = status
        if item_count is not None:
            stage["item_count"] = item_count
        if duration_ms is not None:
            stage["duration_ms"] = duration_ms
        if message:
            stage["message"] = message
        if status in {"cached", "completed"}:
            stage["cache_reusable"] = bool(stage.get("artifact"))
        return


def _write_pipeline_status(
    artifact_path: Path,
    session_id: str,
    stages: list[dict[str, Any]],
    timings: dict[str, int],
    cache_hits: dict[str, bool],
    source_signature: dict[str, Any],
) -> None:
    _write_json(
        artifact_path / "pipeline_status.json",
        {
            "session_id": session_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "source_signature": source_signature,
            "stages": stages,
            "timings": timings,
            "cache_hits": cache_hits,
        },
    )


def _cache_source_matches(artifact_path: Path, source_signature: dict[str, Any]) -> bool:
    persisted = _read_json_object(artifact_path / "pipeline_status.json")
    if not persisted:
        return True
    previous = persisted.get("source_signature")
    if not isinstance(previous, dict):
        return True
    return previous == source_signature


def _clear_pipeline_cache(artifact_path: Path) -> None:
    names = {stage["artifact"] for stage in PIPELINE_STAGE_DEFS if stage["artifact"]}
    names.update(
        {
            "langextract_fact_index.json",
            "cross_chapter_findings.json",
            "pipeline_status.json",
        }
    )
    for name in names:
        target = artifact_path / name
        if not target.exists() or not target.is_file():
            continue
        try:
            target.unlink()
        except Exception:
            logger.warning("water_review_cache_delete_failed path=%s", target, exc_info=True)


def _source_signature(file_path: str | None) -> dict[str, Any]:
    path = Path(file_path) if file_path else None
    if not path or not path.exists():
        return {"path": str(file_path or ""), "exists": False}
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _load_cached_dataclass_list(path: Path, model: type[Any]) -> list[Any] | None:
    data = _read_json_list(path)
    if data is None:
        return None
    allowed = {field.name for field in dataclass_fields(model)}
    items: list[Any] = []
    try:
        for item in data:
            if not isinstance(item, dict):
                return None
            items.append(model(**{key: value for key, value in item.items() if key in allowed}))
    except Exception:
        logger.warning("water_review_cache_invalid path=%s model=%s", path, model.__name__, exc_info=True)
        return None
    return items


def _load_cached_prerag_artifacts(
    artifact_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]] | None:
    fields = _read_json_list(artifact_path / "extracted_fields.json")
    facts = _read_json_list(artifact_path / "langextract_facts.json")
    fact_index = _read_json_object(artifact_path / "langextract_fact_index.json")
    findings = _read_json_list(artifact_path / "cross_chapter_findings.json")
    if fields is None or facts is None or fact_index is None or findings is None:
        return None
    return fields, facts, fact_index, findings


def _read_json_list(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("water_review_cache_json_read_failed path=%s", path, exc_info=True)
        return None
    if not isinstance(data, list):
        return None
    return [item for item in data if isinstance(item, dict)]


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("water_review_cache_json_read_failed path=%s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _json_artifact_count(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("fact_count", "chunk_count", "issue_count", "rule_count"):
            if isinstance(data.get(key), int):
                return int(data[key])
        return len(data)
    return None


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
