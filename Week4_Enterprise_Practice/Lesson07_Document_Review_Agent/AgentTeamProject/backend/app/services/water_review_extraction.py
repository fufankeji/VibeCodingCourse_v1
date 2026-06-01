"""Deterministic field extraction helpers for water review."""

from __future__ import annotations

import re
from typing import Any

from app.services.water_review_models import ReviewChunk, WATER_FIELDS

CORE_EXTRACTION_FIELDS = {
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

def extract_fields(chunks: list[ReviewChunk]) -> list[dict[str, Any]]:
    extracted = [
        _field("project_name", _match_after_chunks(chunks, [r"项目名称[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("construction_unit", _match_after_chunks(chunks, [r"建设单位[:：]?\s*([^\n，。；;]+)", r"建设方[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("construction_location", _match_after_chunks(chunks, [r"建设地点[:：]?\s*([^\n，。；;]+)", r"项目地点[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("project_nature", _match_after_chunks(chunks, [r"建设性质[:：]?\s*([^\n，。；;]+)", r"项目性质[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("disturbed_area", _match_metric_chunks(chunks, ["扰动地表面积", "扰动面积", "防治责任范围"]), chunks),
        _field("land_area", _match_metric_chunks(chunks, ["占地面积", "总占地"]), chunks),
        _field("prevention_responsibility_area", _match_metric_chunks(chunks, ["防治责任范围面积", "防治责任范围"]), chunks),
        _field("excavation_volume", _match_metric_chunks(chunks, ["挖方", "开挖量"]), chunks),
        _field("fill_volume", _match_metric_chunks(chunks, ["填方", "回填量"]), chunks),
        _field("borrow_volume", _match_metric_chunks(chunks, ["借方", "取土量"]), chunks),
        _field("spoil_volume", _match_metric_chunks(chunks, ["弃方", "弃渣量", "弃土量"]), chunks),
    ]

    keyword_fields = {
        "comprehensive_utilization": ["综合利用"],
        "spoil_destination": ["外运", "消纳场", "弃土去向", "弃方去向"],
        "borrow_area": ["取土场"],
    }
    for name, keywords in keyword_fields.items():
        extracted.append(_field(name, _match_keyword_chunks(chunks, keywords), chunks))

    present = {item["field_name"]: item for item in extracted if item["field_name"] in CORE_EXTRACTION_FIELDS}
    return [present.get(name) or _field(name, None, chunks) for name in WATER_FIELDS]

def _field(name: str, match: dict[str, Any] | None, chunks: list[ReviewChunk]) -> dict[str, Any]:
    if not match:
        return {
            "field_name": name,
            "value": "",
            "normalized_value": "",
            "source_span": None,
            "section": "",
            "confidence": 35,
        }
    chunk = _chunk_for_span(chunks, match["start"])
    return {
        "field_name": name,
        "value": match["value"],
        "normalized_value": match.get("normalized_value", match["value"]),
        "source_span": {"char_start": match["start"], "char_end": match["end"]},
        "section": chunk.section if chunk else "",
        "confidence": match.get("confidence", 78),
    }


def _match_after(text: str, patterns: list[str]) -> dict[str, Any] | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            return {"value": value, "start": match.start(1), "end": match.end(1), "confidence": 82}
    return None


def _match_after_chunks(chunks: list[ReviewChunk], patterns: list[str]) -> dict[str, Any] | None:
    for chunk in chunks:
        match = _match_after(chunk.text, patterns)
        if match:
            return _global_match(match, chunk)
    return None


def _match_metric(text: str, labels: list[str]) -> dict[str, Any] | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = rf"({label_pattern})[^\d一二三四五六七八九十零〇百千万亿]{{0,12}}(\d+(?:\.\d+)?)\s*([万亿]?(?:m3|m³|立方米|万m3|万m³|hm2|hm²|公顷|亩|万元|元)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    value = (match.group(2) + (match.group(3) or "")).strip()
    return {
        "value": value,
        "normalized_value": match.group(2),
        "start": match.start(2),
        "end": match.end(3),
        "confidence": 76,
    }


def _match_metric_chunks(chunks: list[ReviewChunk], labels: list[str]) -> dict[str, Any] | None:
    for chunk in chunks:
        match = _match_metric(chunk.text, labels)
        if match:
            return _global_match(match, chunk)
    return None


def _match_keyword(text: str, keywords: list[str]) -> dict[str, Any] | None:
    for keyword in keywords:
        idx = text.find(keyword)
        if idx >= 0:
            return {"value": keyword, "start": idx, "end": idx + len(keyword), "confidence": 70}
    return None


def _match_keyword_chunks(chunks: list[ReviewChunk], keywords: list[str]) -> dict[str, Any] | None:
    for chunk in chunks:
        match = _match_keyword(chunk.text, keywords)
        if match:
            return _global_match(match, chunk)
    return None


def _global_match(match: dict[str, Any], chunk: ReviewChunk) -> dict[str, Any]:
    offset = chunk.char_start
    adjusted = dict(match)
    adjusted["start"] = offset + int(match["start"])
    adjusted["end"] = offset + int(match["end"])
    return adjusted


def _chunk_for_span(chunks: list[ReviewChunk], offset: int) -> ReviewChunk | None:
    for chunk in chunks:
        if chunk.char_start <= offset <= chunk.char_end:
            return chunk
    return chunks[0] if chunks else None


def _best_chunk(chunks: list[ReviewChunk], keywords: list[str]) -> ReviewChunk | None:
    for keyword in keywords:
        for chunk in chunks:
            if keyword in chunk.text or keyword in chunk.section:
                return chunk
    return chunks[0] if chunks else None

def _to_number(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
