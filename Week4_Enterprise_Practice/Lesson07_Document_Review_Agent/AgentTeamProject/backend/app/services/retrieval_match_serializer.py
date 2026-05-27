"""Serialize retrieval matches into the public evidence-location shape."""

from __future__ import annotations

import json
from typing import Any


def serialize_retrieval_match(match: dict[str, Any]) -> dict[str, Any]:
    meta = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    anchors = anchors_from_metadata(meta)
    block_ids = [anchor["block_id"] for anchor in anchors if anchor.get("block_id")]
    page_start = meta.get("page_start")
    page_end = meta.get("page_end")
    return {
        "chunk_id": match.get("chunk_id"),
        "page": page_start,
        "page_end": page_end,
        "primary_page": page_start,
        "page_range": [page_start, page_end] if page_start is not None and page_end is not None else [],
        "chunk_index": meta.get("chunk_index"),
        "section": meta.get("section"),
        "anchors": anchors,
        "block_ids": block_ids,
        "bbox_count": len(anchors),
        "score": match.get("score"),
        "vector_score": match.get("vector_score"),
        "bm25_score": match.get("bm25_score"),
        "vector_rank": match.get("vector_rank"),
        "bm25_rank": match.get("bm25_rank"),
        "neighbor_rank": match.get("neighbor_rank"),
        "final_rank": match.get("final_rank"),
        "retrieval_sources": match.get("retrieval_sources") if isinstance(match.get("retrieval_sources"), list) else [],
        "source_ranks": match.get("source_ranks") if isinstance(match.get("source_ranks"), dict) else {},
        "rerank_score": match.get("rerank_score"),
        "rerank_rank": match.get("rerank_rank"),
        "neighbor_of": match.get("neighbor_of"),
        "text": str(match.get("document", ""))[:1600],
    }


def serialize_retrieval_location(match: dict[str, Any]) -> dict[str, Any]:
    meta = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    anchors = anchors_from_metadata(meta)
    return {
        "chunk_id": match.get("chunk_id"),
        "page_number": meta.get("page_start"),
        "page_end": meta.get("page_end"),
        "paragraph_index": meta.get("chunk_index"),
        "highlight_anchor": match.get("chunk_id"),
        "section": meta.get("section"),
        "anchors": anchors,
        "block_ids": [anchor["block_id"] for anchor in anchors if anchor.get("block_id")],
        "bbox_count": len(anchors),
    }


def anchors_from_metadata(meta: dict[str, Any]) -> list[dict[str, Any]]:
    raw_bboxes = _loads_json_list(meta.get("bbox_json"))
    anchors: list[dict[str, Any]] = []
    for raw in raw_bboxes:
        if not isinstance(raw, dict):
            continue
        raw_page = raw.get("page")
        bbox = raw.get("bbox")
        if not isinstance(raw_page, (int, float)) or not isinstance(bbox, list):
            continue
        anchors.append(
            {
                "page": int(raw_page),
                "block_id": raw.get("block_id"),
                "bbox": bbox,
                "coordinate_mode": "page_coordinate",
                "page_width": raw.get("page_width"),
                "page_height": raw.get("page_height"),
            }
        )
    return anchors


def _loads_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
