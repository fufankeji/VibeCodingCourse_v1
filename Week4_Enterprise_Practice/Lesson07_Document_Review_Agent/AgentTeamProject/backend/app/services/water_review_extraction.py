"""Deterministic field extraction helpers for water review."""

from __future__ import annotations

import re
from typing import Any

from app.services.water_review_models import ReviewChunk, WATER_FIELDS

def extract_fields(chunks: list[ReviewChunk]) -> list[dict[str, Any]]:
    text = "\n".join(chunk.text for chunk in chunks)
    extracted = [
        _field("project_name", _match_after(text, [r"项目名称[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("construction_unit", _match_after(text, [r"建设单位[:：]?\s*([^\n，。；;]+)", r"建设方[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("construction_location", _match_after(text, [r"建设地点[:：]?\s*([^\n，。；;]+)", r"项目地点[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("project_nature", _match_after(text, [r"建设性质[:：]?\s*([^\n，。；;]+)", r"项目性质[:：]?\s*([^\n，。；;]+)"]), chunks),
        _field("disturbed_area", _match_metric(text, ["扰动地表面积", "扰动面积", "防治责任范围"]), chunks),
        _field("land_area", _match_metric(text, ["占地面积", "总占地"]), chunks),
        _field("prevention_responsibility_area", _match_metric(text, ["防治责任范围面积", "防治责任范围"]), chunks),
        _field("zone_area", _match_metric(text, ["分区面积", "防治分区"]), chunks),
        _field("excavation_volume", _match_metric(text, ["挖方", "开挖量"]), chunks),
        _field("fill_volume", _match_metric(text, ["填方", "回填量"]), chunks),
        _field("borrow_volume", _match_metric(text, ["借方", "取土量"]), chunks),
        _field("spoil_volume", _match_metric(text, ["弃方", "弃渣量", "弃土量"]), chunks),
        _field("investment_estimate", _match_metric(text, ["投资估算", "水土保持投资", "总投资"]), chunks),
    ]

    keyword_fields = {
        "key_prevention_or_control_area": ["重点预防区", "重点治理区", "易发生水土流失"],
        "topsoil_stripping": ["表土剥离"],
        "topsoil_preservation": ["表土保存", "表土临时堆存", "表土堆存"],
        "topsoil_backfill": ["表土回覆", "表土回填"],
        "comprehensive_utilization": ["综合利用"],
        "spoil_destination": ["外运", "消纳场", "弃土去向", "弃方去向"],
        "temp_soil_stockpile": ["临时堆土区", "临时堆土场"],
        "borrow_area": ["取土场"],
        "spoil_area": ["弃渣场", "弃土场"],
        "construction_road": ["施工道路", "施工便道"],
        "prevention_measures": ["工程措施", "植物措施", "临时措施", "防治措施"],
        "monitoring": ["水土保持监测", "监测"],
        "schedule_arrangement": ["时序安排", "施工时序", "实施进度"],
    }
    for name, keywords in keyword_fields.items():
        extracted.append(_field(name, _match_keyword(text, keywords), chunks))

    present = {item["field_name"]: item for item in extracted}
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


def _match_keyword(text: str, keywords: list[str]) -> dict[str, Any] | None:
    for keyword in keywords:
        idx = text.find(keyword)
        if idx >= 0:
            return {"value": keyword, "start": idx, "end": idx + len(keyword), "confidence": 70}
    return None


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
