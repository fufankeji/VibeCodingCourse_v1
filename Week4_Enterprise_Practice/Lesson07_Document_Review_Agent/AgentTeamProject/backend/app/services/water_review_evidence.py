"""Evidence match normalization and source-location helpers."""

from __future__ import annotations

import re
from typing import Any

from app.services.water_review_models import ReviewChunk

def _evidence_matches_from_slot_package(
    evidence_slot_package: dict[str, Any],
    chunks: list[ReviewChunk],
    limit: int = 8,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in evidence_slot_package.get("slots", []):
        if not isinstance(slot, dict):
            continue
        for key in ["prompt_matches", "trace_matches", "matches"]:
            for match in slot.get(key, []):
                if not isinstance(match, dict):
                    continue
                chunk_id = str(match.get("chunk_id") or "")
                if chunk_id and chunk_id in seen:
                    continue
                seen.add(chunk_id)
                enriched = dict(match)
                enriched["slot_id"] = slot.get("slot_id")
                enriched["slot_label"] = slot.get("label")
                if not enriched.get("anchors"):
                    chunk = _chunk_for_evidence_match(chunks, enriched)
                    if chunk:
                        enriched.update(_evidence_match_from_chunk(chunk, []))
                matches.append(enriched)
                if len(matches) >= limit:
                    return matches
    return matches


def _evidence_matches_from_chunks(
    chunks: list[ReviewChunk],
    keywords: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, ReviewChunk, list[str]]] = []
    normalized_keywords = [keyword for keyword in keywords if keyword]
    for index, chunk in enumerate(chunks):
        text = chunk.text or ""
        matched_terms = [keyword for keyword in normalized_keywords if keyword in text]
        if not matched_terms:
            continue
        scored.append((len(matched_terms), -index, chunk, matched_terms))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [_evidence_match_from_chunk(chunk, matched_terms) for _, _, chunk, matched_terms in scored[:limit]]


def _evidence_matches_from_chunk(chunk: ReviewChunk | None) -> list[dict[str, Any]]:
    return [_evidence_match_from_chunk(chunk, [])] if chunk else []


def _evidence_match_from_chunk(chunk: ReviewChunk, matched_terms: list[str]) -> dict[str, Any]:
    page_start = chunk.page_range[0] if chunk.page_range else None
    page_end = chunk.page_range[-1] if chunk.page_range else page_start
    anchors = chunk.bbox_list or []
    block_ids = [str(anchor.get("block_id")) for anchor in anchors if anchor.get("block_id")]
    return {
        "chunk_id": chunk.chunk_id,
        "page": page_start,
        "page_end": page_end,
        "primary_page": page_start,
        "page_range": [page_start, page_end] if page_start is not None and page_end is not None else [],
        "section": chunk.section,
        "anchors": anchors,
        "block_ids": block_ids,
        "bbox_count": len(anchors),
        "matched_terms": matched_terms,
        "retrieval_sources": ["keyword"],
        "text": chunk.text[:1600],
    }


def _chunk_for_evidence_match(chunks: list[ReviewChunk], match: dict[str, Any]) -> ReviewChunk | None:
    chunk_id = str(match.get("chunk_id") or "")
    if not chunk_id:
        return None
    return next((chunk for chunk in chunks if chunk.chunk_id == chunk_id), None)


def _source_bbox_list_from_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in matches:
        for anchor in match.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            key = f"{anchor.get('page')}:{anchor.get('block_id')}:{anchor.get('bbox')}"
            if key in seen:
                continue
            seen.add(key)
            anchors.append(anchor)
    return anchors


def _block_ids_from_matches(matches: list[dict[str, Any]]) -> list[str]:
    block_ids: list[str] = []
    seen: set[str] = set()
    for match in matches:
        candidates = match.get("block_ids")
        if not isinstance(candidates, list):
            candidates = [anchor.get("block_id") for anchor in match.get("anchors", []) if isinstance(anchor, dict)]
        for block_id in candidates:
            text = str(block_id or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            block_ids.append(text)
    return block_ids


def _source_pages_from_matches(matches: list[dict[str, Any]]) -> list[int]:
    pages: set[int] = set()
    for match in matches:
        for key in ["page", "primary_page"]:
            value = match.get(key)
            if isinstance(value, int):
                pages.add(value)
        page_range = match.get("page_range")
        if isinstance(page_range, list):
            pages.update(int(page) for page in page_range if isinstance(page, int))
    return sorted(page for page in pages if page > 0)


def _evidence_text_from_matches(matches: list[dict[str, Any]], limit: int = 5) -> str:
    lines: list[str] = []
    for index, match in enumerate(matches[:limit], start=1):
        page = match.get("page") or match.get("primary_page") or "-"
        chunk_id = str(match.get("chunk_id") or "-")
        section = str(match.get("section") or "").strip()
        text = re.sub(r"\s+", " ", str(match.get("text") or "")).strip()
        if not text:
            continue
        prefix = f"{index}. {chunk_id} p.{page}"
        if section:
            prefix += f" {section}"
        lines.append(f"{prefix}：{text[:320]}")
    return "\n".join(lines)
