"""Machine-readable golden evidence annotations for offline review evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GoldenEvidenceError(ValueError):
    """Raised when a golden evidence set is not machine-readable."""


def load_golden_evidence_set(path: str | Path) -> dict[str, Any]:
    data = _read_json(path)
    documents = _list(data, "documents", "root")
    normalized_documents = [_normalize_document(document, index) for index, document in enumerate(documents)]
    check_item_count = sum(len(document["check_items"]) for document in normalized_documents)
    evidence_count = sum(
        len(check_item["evidence"])
        for document in normalized_documents
        for check_item in document["check_items"]
    )
    return {
        "version": int(data.get("version") or 1),
        "document_count": len(normalized_documents),
        "check_item_count": check_item_count,
        "evidence_count": evidence_count,
        "documents": normalized_documents,
    }


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoldenEvidenceError(f"golden evidence file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GoldenEvidenceError(f"golden evidence file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GoldenEvidenceError("golden evidence root must be an object")
    return data


def _normalize_document(document: Any, index: int) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise GoldenEvidenceError(f"documents[{index}] must be an object")
    context = f"documents[{index}]"
    document_id = _required_string(document, "document_id", context)
    check_items = _list(document, "check_items", context)
    return {
        "document_id": document_id,
        "title": str(document.get("title") or ""),
        "check_items": [
            _normalize_check_item(check_item, f"{context}.check_items[{check_index}]")
            for check_index, check_item in enumerate(check_items)
        ],
    }


def _normalize_check_item(check_item: Any, context: str) -> dict[str, Any]:
    if not isinstance(check_item, dict):
        raise GoldenEvidenceError(f"{context} must be an object")
    check_item_id = _required_string(check_item, "check_item_id", context)
    evidence_items = _list(check_item, "evidence", context)
    normalized_evidence = []
    seen_slot_ids: set[str] = set()
    for evidence_index, evidence in enumerate(evidence_items):
        normalized = _normalize_evidence(evidence, f"{context}.evidence[{evidence_index}]")
        slot_id = normalized["evidence_slot_id"]
        if slot_id in seen_slot_ids:
            raise GoldenEvidenceError(f"{context}.evidence duplicate evidence_slot_id: {slot_id}")
        seen_slot_ids.add(slot_id)
        normalized_evidence.append(normalized)
    return {
        "check_item_id": check_item_id,
        "evidence": normalized_evidence,
    }


def _normalize_evidence(evidence: Any, context: str) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise GoldenEvidenceError(f"{context} must be an object")
    page = _positive_int(evidence.get("page"), f"{context}.page")
    chunk_id = str(evidence.get("chunk_id") or "").strip()
    block_id = str(evidence.get("block_id") or "").strip()
    if not chunk_id and not block_id:
        raise GoldenEvidenceError(f"{context} must include chunk_id or block_id")
    return {
        "evidence_slot_id": _required_string(evidence, "evidence_slot_id", context),
        "page": page,
        "chunk_id": chunk_id,
        "block_id": block_id,
        "expected_text": _required_string(evidence, "expected_text", context),
    }


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise GoldenEvidenceError(f"{context}.{key} is required")
    return value


def _list(data: dict[str, Any], key: str, context: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise GoldenEvidenceError(f"{context}.{key} must be a non-empty list")
    return value


def _positive_int(value: Any, context: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GoldenEvidenceError(f"{context} must be a positive integer") from exc
    if parsed < 1:
        raise GoldenEvidenceError(f"{context} must be a positive integer")
    return parsed
