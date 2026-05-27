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
from app.services.retrieval_match_serializer import serialize_retrieval_match
from app.services.water_review_service import ReviewChunk


class RetrievalDebugBadRequest(ValueError):
    """Raised when retrieval debug cannot run for the current request."""


def run_retrieval_debug(
    session_id: str,
    query: str,
    db: Session,
    top_k: int = 8,
    use_rerank: bool = True,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalDebugBadRequest("query 不能为空")
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
    vector_available = _vector_store_exists(vector_dir)
    store = (
        rag_service.ChromaChunkStore(vector_dir, session_id, rag_service.SiliconFlowEmbeddingProvider())
        if vector_available
        else None
    )
    bounded_top_k = max(1, min(requested_top_k, 20))
    retrieval = rag_service.retrieve_for_query(
        chunks,
        normalized_query,
        top_k=bounded_top_k,
        store=store,
        use_rerank=use_rerank,
    )
    status = "ready" if retrieval["vector_available"] else "degraded"
    return {
        "status": status,
        "query": normalized_query,
        "matches": [serialize_retrieval_match(match) for match in retrieval["matches"]],
        "trace": {
            "persisted": False,
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
            "artifact_dir": str(artifact_dir),
            "chunk_count": 0,
            "vector_available": False,
            "bm25_available": False,
            "rerank_available": False,
            "retrieval_mode": "unavailable",
        },
    }
