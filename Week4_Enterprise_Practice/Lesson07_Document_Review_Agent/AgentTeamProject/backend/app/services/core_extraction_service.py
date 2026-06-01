"""Select core chunks for focused water-review field extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services import rag_service

logger = logging.getLogger(__name__)

CORE_FIELD_NAMES = {
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "land_area",
    "disturbed_area",
    "prevention_responsibility_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "spoil_destination",
    "borrow_area",
    "comprehensive_utilization",
}

CORE_EXTRACTION_QUERIES = (
    "项目概况 项目名称 建设单位 建设地点 建设性质 占地面积 防治责任范围 扰动面积",
    "土石方平衡 挖方 填方 借方 弃方 余方 外运 消纳 综合利用 取土场 弃渣场",
)

CORE_SECTION_TERMS = (
    "项目概况",
    "综合说明",
    "工程概况",
    "土石方",
    "土石方平衡",
)

CORE_KEYWORDS = (
    "项目名称",
    "建设单位",
    "建设地点",
    "建设性质",
    "占地面积",
    "扰动面积",
    "扰动地表面积",
    "防治责任范围",
    "土石方",
    "挖方",
    "填方",
    "借方",
    "弃方",
    "余方",
    "外运",
    "消纳",
    "综合利用",
    "取土场",
    "弃渣场",
)


@dataclass(frozen=True)
class CoreExtractionSelection:
    chunks: list[Any]
    mode: str
    trace: dict[str, Any]


def build_core_extraction_chunks(
    chunks: list[Any],
    session_id: str,
    artifact_dir: str | Path,
    *,
    store_factory: Callable[[], Any | None] | None = None,
) -> CoreExtractionSelection:
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    if not chunks:
        trace = _trace([], [], "empty", True, errors)
        _write_trace(artifact_path, trace)
        return CoreExtractionSelection([], "empty", trace)

    mode = "vector"
    store = None
    if store_factory is not None:
        try:
            store = store_factory()
        except Exception as exc:
            errors.append(f"vector_unavailable: {exc}")
            logger.info("core_extraction_vector_unavailable session_id=%s error=%s", session_id, exc)

    selected_ids: list[str] = []
    try:
        for query in CORE_EXTRACTION_QUERIES:
            retrieval = rag_service.retrieve_for_query(
                chunks,
                query,
                top_k=min(max(settings.rag_top_k, 8), 16),
                store=store,
                use_bm25=True,
                use_neighbors=True,
                use_rerank=False,
            )
            selected_ids.extend(_selected_ids_from_matches(chunks, retrieval.get("matches", [])))
        if store is None:
            mode = "bm25"
    except Exception as exc:
        errors.append(f"retrieval_failed: {exc}")
        logger.info("core_extraction_retrieval_failed session_id=%s error=%s", session_id, exc)
        selected_ids = []
        mode = "keyword"

    selected = _chunks_by_ids_in_source_order(chunks, selected_ids)
    if not selected:
        selected = _keyword_core_chunks(chunks)
        mode = "keyword"

    fallback_used = store is None or bool(errors) or mode in {"bm25", "keyword"}
    if not selected:
        selected = list(chunks)
        mode = "all_chunks_fallback"
        fallback_used = True

    trace = _trace(chunks, selected, mode, fallback_used, errors)
    _write_trace(artifact_path, trace)
    return CoreExtractionSelection(selected, mode, trace)


def _default_store(chunks: list[Any], session_id: str) -> rag_service.ChromaChunkStore:
    vector_dir = Path(settings.storage_path) / "vector_stores" / "water_review" / session_id
    vector_dir.mkdir(parents=True, exist_ok=True)
    store = rag_service.ChromaChunkStore(vector_dir, session_id, rag_service.SiliconFlowEmbeddingProvider())
    store.rebuild(chunks)
    return store


def _chunks_by_ids_in_source_order(chunks: list[Any], chunk_ids: list[str]) -> list[Any]:
    wanted = {chunk_id for chunk_id in chunk_ids if chunk_id}
    return [chunk for chunk in chunks if str(getattr(chunk, "chunk_id", "")) in wanted]


def _keyword_core_chunks(chunks: list[Any]) -> list[Any]:
    return [chunk for chunk in chunks if _is_core_chunk(chunk)]


def _trace(
    input_chunks: list[Any],
    selected_chunks: list[Any],
    mode: str,
    fallback_used: bool,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "fallback_used": fallback_used,
        "input_count": len(input_chunks),
        "selected_count": len(selected_chunks),
        "queries": list(CORE_EXTRACTION_QUERIES),
        "errors": errors,
        "chunks": [_trace_chunk(chunk) for chunk in selected_chunks],
    }


def _write_trace(artifact_dir: Path, trace: dict[str, Any]) -> None:
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "core_extraction_chunks.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.info("core_extraction_trace_write_failed path=%s error=%s", artifact_dir, exc)


def _selected_ids_from_matches(chunks: list[Any], matches: list[Any]) -> list[str]:
    by_id = {str(getattr(chunk, "chunk_id", "")): chunk for chunk in chunks}
    selected_ids: list[str] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        chunk_id = str(match.get("chunk_id") or "")
        if not chunk_id:
            continue
        if "neighbor" in match.get("retrieval_sources", []) and not _is_core_chunk(by_id.get(chunk_id)):
            continue
        selected_ids.append(chunk_id)
    return selected_ids


def _is_core_chunk(chunk: Any) -> bool:
    if chunk is None:
        return False
    section = str(getattr(chunk, "section", "") or "")
    text = str(getattr(chunk, "text", "") or "")
    haystack = f"{section}\n{text}"
    return any(term in section for term in CORE_SECTION_TERMS) or any(keyword in haystack for keyword in CORE_KEYWORDS)


def _trace_chunk(chunk: Any) -> dict[str, Any]:
    return {
        "chunk_id": str(getattr(chunk, "chunk_id", "") or ""),
        "section": str(getattr(chunk, "section", "") or ""),
        "page_range": list(getattr(chunk, "page_range", []) or []),
    }
