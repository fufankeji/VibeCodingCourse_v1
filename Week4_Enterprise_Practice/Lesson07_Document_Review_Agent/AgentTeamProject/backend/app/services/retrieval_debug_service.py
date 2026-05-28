"""Non-persistent retrieval debug execution for review sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.services import rag_service
from app.services.review_agent_service import build_evidence_slot_package
from app.services.retrieval_match_serializer import serialize_retrieval_match
from app.services.water_review_service import ReviewChunk


class RetrievalDebugBadRequest(ValueError):
    """Raised when retrieval debug cannot run for the current request."""


def run_retrieval_debug(
    session_id: str,
    query: str,
    db: Session,
    evidence_slot: dict[str, Any] | None = None,
    top_k: int = 8,
    use_vector: bool = True,
    use_bm25: bool = True,
    use_neighbors: bool = True,
    use_rerank: bool = True,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query and not evidence_slot:
        raise RetrievalDebugBadRequest("query 或 evidence_slot 不能为空")
    if not use_vector and not use_bm25:
        raise RetrievalDebugBadRequest("至少启用 BM25 或向量检索")
    requested_top_k = int(top_k)

    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise RetrievalDebugBadRequest("当前 session 不存在")
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise RetrievalDebugBadRequest("当前 session 缺少关联方案文件")

    artifact_dir = _artifact_dir_for_contract(contract)
    chunks = _load_review_chunks(artifact_dir / "review_chunks.json")
    if not chunks:
        return _unavailable_response(normalized_query, "review_chunks_missing", artifact_dir)

    vector_dir = Path(settings.storage_path) / "vector_stores" / "water_review" / session_id
    vector_available = bool(use_vector and _vector_store_exists(vector_dir))
    store = (
        rag_service.ChromaChunkStore(vector_dir, session_id, rag_service.SiliconFlowEmbeddingProvider())
        if vector_available
        else None
    )
    if evidence_slot:
        return _run_evidence_slot_debug(
            evidence_slot,
            chunks,
            store,
            normalized_query,
            requested_top_k,
            artifact_dir,
            vector_dir,
            vector_available,
            use_vector,
            use_bm25,
            use_neighbors,
            use_rerank,
        )
    bounded_top_k = max(1, min(requested_top_k, 20))
    retrieval = rag_service.retrieve_for_query(
        chunks,
        normalized_query,
        top_k=bounded_top_k,
        store=store,
        use_bm25=use_bm25,
        use_neighbors=use_neighbors,
        use_rerank=use_rerank,
    )
    status = "degraded" if use_vector and not retrieval["vector_available"] else "ready"
    return {
        "status": status,
        "query": normalized_query,
        "matches": [serialize_retrieval_match(match) for match in retrieval["matches"]],
        "trace": {
            "persisted": False,
            "debug_mode": "query",
            "artifact_dir": str(artifact_dir),
            "chunk_count": len(chunks),
            "vector_store": str(vector_dir),
            "vector_available": retrieval["vector_available"],
            "bm25_available": retrieval["bm25_available"],
            "rerank_available": retrieval["rerank_available"],
            "retrieval_mode": retrieval["retrieval_mode"],
            "top_k": bounded_top_k,
            "requested_top_k": requested_top_k,
            "top_k_clamped": requested_top_k != bounded_top_k,
            "requested_use_vector": use_vector,
            "requested_use_bm25": use_bm25,
            "requested_use_neighbors": use_neighbors,
            "requested_use_rerank": use_rerank,
        },
    }


def _run_evidence_slot_debug(
    evidence_slot: dict[str, Any],
    chunks: list[ReviewChunk],
    store: rag_service.ChromaChunkStore | None,
    query: str,
    requested_top_k: int,
    artifact_dir: Path,
    vector_dir: Path,
    vector_available: bool,
    use_vector: bool,
    use_bm25: bool,
    use_neighbors: bool,
    use_rerank: bool,
) -> dict[str, Any]:
    slot = dict(evidence_slot)
    if query and not slot.get("queries"):
        slot["queries"] = [query]
    package = build_evidence_slot_package(
        {"evidence_slots": [slot]},
        chunks,
        store if use_vector else None,
        use_bm25=use_bm25,
        use_neighbors=use_neighbors,
        use_rerank=use_rerank,
    )
    first_slot = package["slots"][0] if package.get("slots") else {}
    first_query = ""
    queries = first_slot.get("queries") if isinstance(first_slot, dict) else []
    if isinstance(queries, list) and queries:
        first_query = str(queries[0].get("query") or "") if isinstance(queries[0], dict) else ""
    matches = first_slot.get("matches") if isinstance(first_slot, dict) else []
    if not isinstance(matches, list):
        matches = []
    query_traces = [item for item in queries if isinstance(item, dict)] if isinstance(queries, list) else []
    vector_used = bool(vector_available and use_vector)
    rerank_available = any(bool(item.get("matches")) for item in query_traces) and vector_used and use_rerank and bool(settings.siliconflow_reranker_model)
    return {
        "status": "degraded" if use_vector and not vector_available else "ready",
        "query": first_query or query,
        "matches": matches,
        "evidence_slot_package": package,
        "trace": {
            "persisted": False,
            "debug_mode": "evidence_slot",
            "artifact_dir": str(artifact_dir),
            "chunk_count": len(chunks),
            "vector_store": str(vector_dir),
            "vector_available": vector_used,
            "bm25_available": use_bm25,
            "rerank_available": rerank_available,
            "retrieval_mode": query_traces[0].get("retrieval_mode", "") if query_traces else "",
            "top_k": settings.rag_top_k,
            "slot_top_k": settings.rag_top_k,
            "requested_top_k": requested_top_k,
            "top_k_clamped": False,
            "requested_use_vector": use_vector,
            "requested_use_bm25": use_bm25,
            "requested_use_neighbors": use_neighbors,
            "requested_use_rerank": use_rerank,
        },
    }


def _artifact_dir_for_contract(contract: Contract) -> Path:
    storage_artifact_dir = Path(settings.storage_path) / "contracts" / contract.id / "water_review"
    candidates = [storage_artifact_dir]
    if contract.file_path:
        file_path = Path(contract.file_path)
        candidates.append(file_path.parent / "water_review")
        if not file_path.is_absolute():
            candidates.append(Path.cwd() / file_path.parent / "water_review")
    for candidate in candidates:
        if (candidate / "review_chunks.json").exists():
            return candidate
    return storage_artifact_dir


def _load_review_chunks(path: Path) -> list[ReviewChunk]:
    items = _load_json_list(path)
    chunks: list[ReviewChunk] = []
    for item in items:
        try:
            chunks.append(
                ReviewChunk(
                    chunk_id=str(item.get("chunk_id") or ""),
                    text=str(item.get("text") or ""),
                    section=str(item.get("section") or ""),
                    page_range=[int(page) for page in item.get("page_range", [])] or [1, 1],
                    bbox_list=item.get("bbox_list") if isinstance(item.get("bbox_list"), list) else [],
                    table_refs=item.get("table_refs") if isinstance(item.get("table_refs"), list) else [],
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    char_start=int(item.get("char_start") or 0),
                    char_end=int(item.get("char_end") or 0),
                )
            )
        except Exception:
            continue
    return [chunk for chunk in chunks if chunk.chunk_id and chunk.text.strip()]


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _vector_store_exists(vector_dir: Path) -> bool:
    return vector_dir.exists() and any(vector_dir.iterdir())


def _unavailable_response(query: str, reason: str, artifact_dir: Path) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "query": query,
        "reason": reason,
        "matches": [],
        "trace": {
            "persisted": False,
            "debug_mode": "query",
            "artifact_dir": str(artifact_dir),
            "chunk_count": 0,
            "vector_available": False,
            "bm25_available": False,
            "rerank_available": False,
            "retrieval_mode": "unavailable",
        },
    }
