"""Deterministic project-composition consistency checks."""

from __future__ import annotations

import re
from typing import Any


AREA_FIELDS = {
    "total_building_area": "总建筑面积",
    "above_ground_building_area": "地上建筑面积",
    "underground_building_area": "地下建筑面积",
}

JUDGEMENT_BASIS = (
    "规则要求：项目组成及建设内容应与立项文件或所处阶段的主体设计文件一致。"
    "判定方法：抽取正文项目概况与附件/主体设计文件中的关键建设规模字段，逐字段比较数值，差异超过 0.1 平方米判为不一致。"
)


def analyze_project_composition_consistency(chunks: list[Any], check_item: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_project_composition_check(check_item):
        return None

    body = _select_body_source(chunks)
    reference = _select_reference_source(chunks)
    if not body or not reference:
        return {
            "status": "needs_review",
            "reason": "未同时定位到项目概况正文和立项/主体设计附件证据。",
            "judgement_basis": JUDGEMENT_BASIS,
            "body_source": _source_summary(body) if body else None,
            "reference_source": _source_summary(reference) if reference else None,
            "evidence_quotes": _evidence_quotes(body, reference),
            "field_comparisons": [],
            "key_findings": [],
        }

    body_fields = _extract_project_fields(_chunk_text(body))
    reference_fields = _extract_project_fields(_chunk_text(reference))
    comparisons = [
        _compare_number_field(field, label, body_fields.get(field), reference_fields.get(field))
        for field, label in AREA_FIELDS.items()
    ]
    statuses = {item["status"] for item in comparisons}
    if "mismatch" in statuses:
        status = "mismatch"
    elif "missing" in statuses:
        status = "needs_review"
    else:
        status = "match"

    return {
        "status": status,
        "reason": _comparison_reason(status, comparisons),
        "judgement_basis": JUDGEMENT_BASIS,
        "body_source": _source_summary(body, material_type="document_body"),
        "reference_source": _source_summary(reference),
        "evidence_quotes": _evidence_quotes(body, reference),
        "field_comparisons": comparisons,
        "key_findings": _key_findings(comparisons),
    }


def _is_project_composition_check(check_item: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(check_item.get("review_type") or ""),
            str(check_item.get("review_sub_type") or ""),
            str(check_item.get("review_criteria") or ""),
            str(check_item.get("expected_result") or ""),
            " ".join(str(item) for item in check_item.get("target_fields", []) if item),
        ]
    )
    return all(keyword in text for keyword in ["项目", "建设"]) and any(
        keyword in text for keyword in ["组成", "建设内容", "立项", "主体设计"]
    )


def _select_body_source(chunks: list[Any]) -> Any | None:
    candidates = [
        chunk
        for chunk in chunks
        if "建设内容" in _chunk_text(chunk)
        and any(keyword in _chunk_text(chunk) for keyword in ["建设项目名称", "建设规模", "总建筑面积"])
    ]
    return candidates[0] if candidates else None


def _select_reference_source(chunks: list[Any]) -> Any | None:
    candidates = [
        chunk
        for chunk in chunks
        if _reference_material_type(chunk) != "unknown"
        and any(keyword in _chunk_text(chunk) for keyword in ["建筑面积", "建设规模", "居住用地"])
    ]
    candidates.sort(key=lambda chunk: _reference_priority(_reference_material_type(chunk)))
    return candidates[0] if candidates else None


def _reference_material_type(chunk: Any) -> str:
    section = _chunk_section(chunk)
    text = f"{section}\n{_chunk_text(chunk)[:500]}"
    if "可行性研究" in section and "批复" in section:
        return "feasibility_reply"
    if "初步设计" in section and "批复" in section:
        return "preliminary_design_reply"
    if "可行性研究" in text and "批复" in text:
        return "feasibility_reply"
    if "初步设计" in text and "批复" in text:
        return "preliminary_design_reply"
    if "立项" in text or "选址规划意见书" in text:
        return "approval_file"
    if "主体设计" in text or "施工图设计" in text:
        return "design_file"
    return "unknown"


def _reference_priority(material_type: str) -> int:
    return {
        "preliminary_design_reply": 0,
        "feasibility_reply": 1,
        "approval_file": 2,
        "design_file": 3,
    }.get(material_type, 99)


def _extract_project_fields(text: str) -> dict[str, float]:
    normalized = _normalize_text(text)
    return {
        "total_building_area": _find_area(normalized, [r"建设规模[:：]?总建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?", r"核定项目建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?", r"项目建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?", r"总建筑规模为([0-9.]+)(?:平方米|㎡|m\^2)?", r"总建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?"]),
        "above_ground_building_area": _find_area(normalized, [r"地上建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?", r"地上住宅及居住公共服务设施建筑面积约?([0-9.]+)(?:平方米|㎡|m\^2)?"]),
        "underground_building_area": _find_area(normalized, [r"地下建筑面积(?:为)?([0-9.]+)(?:平方米|㎡|m\^2)?"]),
    }


def _find_area(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return round(float(match.group(1)), 2)
            except ValueError:
                return None
    return None


def _compare_number_field(field: str, label: str, body_value: float | None, reference_value: float | None) -> dict[str, Any]:
    if body_value is None or reference_value is None:
        status = "missing"
        difference = None
    else:
        difference = round(body_value - reference_value, 2)
        status = "match" if abs(difference) <= 0.1 else "mismatch"
    return {
        "field": field,
        "label": label,
        "status": status,
        "body_value": body_value,
        "reference_value": reference_value,
        "difference": difference,
    }


def _comparison_reason(status: str, comparisons: list[dict[str, Any]]) -> str:
    if status == "match":
        details = _comparison_details([item for item in comparisons if item["status"] == "match"])
        return "正文项目概况与所选附件/主体设计文件的关键建设规模一致。" + (f" {details}" if details else "")
    if status == "mismatch":
        details = _comparison_details([item for item in comparisons if item["status"] == "mismatch"])
        return "正文项目概况与所选附件/主体设计文件存在关键建设规模差异。" + (f" {details}" if details else "")
    details = _comparison_details([item for item in comparisons if item["status"] == "missing"])
    return "正文或附件缺少可结构化比较的关键字段，需人工复核。" + (f" {details}" if details else "")


def _key_findings(comparisons: list[dict[str, Any]]) -> list[str]:
    priority = {"mismatch": 0, "missing": 1, "match": 2}
    ordered = sorted(comparisons, key=lambda item: priority.get(str(item.get("status")), 9))
    return [_comparison_detail(item) for item in ordered if _comparison_detail(item)]


def _comparison_details(comparisons: list[dict[str, Any]]) -> str:
    details = [_comparison_detail(item) for item in comparisons]
    return "；".join(item for item in details if item)


def _comparison_detail(item: dict[str, Any]) -> str:
    label = str(item.get("label") or item.get("field") or "字段")
    status = str(item.get("status") or "")
    body_value = item.get("body_value")
    reference_value = item.get("reference_value")
    difference = item.get("difference")
    if status == "missing":
        return f"{label}：正文 {_format_area(body_value)}，附件/设计 {_format_area(reference_value)}，缺少可比较值"
    if body_value is None or reference_value is None:
        return ""
    if status == "match":
        return f"{label}：正文 {_format_area(body_value)} 与附件/设计 {_format_area(reference_value)}一致"
    return f"{label}：正文 {_format_area(body_value)} vs 附件/设计 {_format_area(reference_value)}，差异 {_format_area(difference)}"


def _format_area(value: Any) -> str:
    if value is None:
        return "未提取"
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        return f"{value} 平方米"
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{text} 平方米"


def _evidence_quotes(body: Any | None, reference: Any | None) -> dict[str, str]:
    return {
        "body": _quote("正文原话", body),
        "reference": _quote("附件/设计原话", reference),
    }


def _quote(label: str, chunk: Any | None) -> str:
    if not chunk:
        return f"{label}：未定位"
    return f"{label}：{_chunk_text(chunk)[:260]}"


def _source_summary(chunk: Any, material_type: str | None = None) -> dict[str, Any]:
    anchors = _anchors(chunk)
    page_range = _chunk_page_range(chunk)
    return {
        "chunk_id": _chunk_id(chunk),
        "section": _chunk_section(chunk),
        "page": page_range[0] if page_range else None,
        "page_end": page_range[-1] if page_range else None,
        "primary_page": page_range[0] if page_range else None,
        "page_range": page_range,
        "material_type": material_type or _reference_material_type(chunk),
        "anchors": anchors,
        "block_ids": [anchor["block_id"] for anchor in anchors if anchor.get("block_id")],
        "bbox_count": len(anchors),
        "text": _chunk_text(chunk)[:800],
    }


def _chunk_id(chunk: Any) -> str:
    return str(getattr(chunk, "chunk_id", "") or "")


def _chunk_text(chunk: Any) -> str:
    return str(getattr(chunk, "text", "") or "")


def _chunk_section(chunk: Any) -> str:
    return str(getattr(chunk, "section", "") or "")


def _chunk_page_range(chunk: Any) -> list[int]:
    value = getattr(chunk, "page_range", []) or []
    return [int(page) for page in value]


def _anchors(chunk: Any) -> list[dict[str, Any]]:
    raw_bboxes = getattr(chunk, "bbox_list", []) or []
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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("\\mathrm", "").replace("{", "").replace("}", ""))
