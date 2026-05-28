"""Evaluate retrieval hits against machine-readable golden evidence."""

from __future__ import annotations

from typing import Any


def evaluate_golden_evidence_retrieval(
    golden_set: dict[str, Any], retrieval_results: dict[str, Any] | None
) -> dict[str, Any]:
    """Evaluate retrieval results against a normalized golden evidence set."""
    documents = []
    hit_count = 0
    check_item_count = 0
    evidence_count = 0

    for document in golden_set.get("documents", []):
        document_id = document["document_id"]
        check_items = []
        for check_item in document.get("check_items", []):
            check_item_count += 1
            check_item_id = check_item["check_item_id"]
            evidence_results = []
            for evidence in check_item.get("evidence", []):
                evidence_count += 1
                matched_by = _matched_by(document_id, check_item_id, evidence, retrieval_results or {})
                if matched_by != "none":
                    hit_count += 1
                evidence_results.append(
                    {
                        "evidence_slot_id": evidence["evidence_slot_id"],
                        "status": "hit" if matched_by != "none" else "miss",
                        "matched_by": matched_by,
                        "chunk_id": evidence.get("chunk_id", ""),
                        "block_id": evidence.get("block_id", ""),
                    }
                )
            check_items.append(
                {
                    "check_item_id": check_item_id,
                    "evidence": evidence_results,
                }
            )
        documents.append(
            {
                "document_id": document_id,
                "check_items": check_items,
            }
        )

    miss_count = evidence_count - hit_count
    return {
        "document_count": len(documents),
        "check_item_count": check_item_count,
        "evidence_count": evidence_count,
        "hit_count": hit_count,
        "miss_count": miss_count,
        "recall": hit_count / evidence_count if evidence_count else 0.0,
        "documents": documents,
    }


def _matched_by(
    document_id: str, check_item_id: str, evidence: dict[str, Any], retrieval_results: dict[str, Any]
) -> str:
    slot_id = evidence["evidence_slot_id"]
    matches = _slot_matches(retrieval_results, document_id, check_item_id, slot_id)
    golden_chunk_id = evidence.get("chunk_id", "")
    golden_block_id = evidence.get("block_id", "")
    for match in matches:
        if golden_chunk_id and golden_chunk_id in _match_chunk_ids(match):
            return "chunk_id"
        if golden_block_id and golden_block_id in _match_block_ids(match):
            return "block_id"
    return "none"


def _slot_matches(
    retrieval_results: dict[str, Any],
    document_id: str,
    check_item_id: str,
    slot_id: str,
) -> list[dict[str, Any]]:
    documents = _dict(retrieval_results.get("documents"))
    document = _dict(documents.get(document_id))
    check_items = _dict(document.get("check_items"))
    check_item = _dict(check_items.get(check_item_id))
    slots = _dict(check_item.get("slots"))
    slot = _dict(slots.get(slot_id))
    matches = slot.get("matches")
    if not isinstance(matches, list):
        return []
    return [match for match in matches if isinstance(match, dict)]


def _match_chunk_ids(match: dict[str, Any]) -> set[str]:
    chunk_ids = _string_set(match.get("chunk_ids"))
    chunk_id = str(match.get("chunk_id") or "").strip()
    if chunk_id:
        chunk_ids.add(chunk_id)
    return chunk_ids


def _match_block_ids(match: dict[str, Any]) -> set[str]:
    block_ids = _string_set(match.get("block_ids"))
    block_id = str(match.get("block_id") or "").strip()
    if block_id:
        block_ids.add(block_id)
    anchors = match.get("anchors")
    if isinstance(anchors, list):
        for anchor in anchors:
            if isinstance(anchor, dict):
                anchor_block_id = str(anchor.get("block_id") or "").strip()
                if anchor_block_id:
                    block_ids.add(anchor_block_id)
    return block_ids


def _string_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value or "").strip()
    return {text} if text else set()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
