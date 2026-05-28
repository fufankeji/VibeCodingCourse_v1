"""Deterministic project-composition consistency checks."""

from __future__ import annotations

import re
from typing import Any


AREA_FIELDS = {
    "total_building_area": "总建筑面积",
    "above_ground_building_area": "地上建筑面积",
    "underground_building_area": "地下建筑面积",
}


def analyze_project_composition_consistency(chunks: list[Any], check_item: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_project_composition_check(check_item):
        return None

    body = _select_body_source(chunks)
    reference = _select_reference_source(chunks)
    if not body or not reference:
        return {
            "status": "needs_review",
            "reason": "未同时定位到项目概况正文和立项/主体设计附件证据。",
            "body_source": _source_summary(body) if body else None,
            "reference_source": _source_summary(reference) if reference else None,
            "field_comparisons": [],
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
        "reason": _comparison_reason(status),
        "body_source": _source_summary(body, material_type="document_body"),
        "reference_source": _source_summary(reference),
        "field_comparisons": comparisons,
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


def _comparison_reason(status: str) -> str:
    if status == "match":
        return "正文项目概况与所选附件/主体设计文件的关键建设规模一致。"
    if status == "mismatch":
        return "正文项目概况与所选附件/主体设计文件存在关键建设规模差异。"
    return "正文或附件缺少可结构化比较的关键字段，需人工复核。"


def _source_summary(chunk: Any, material_type: str | None = None) -> dict[str, Any]:
    return {
        "chunk_id": _chunk_id(chunk),
        "section": _chunk_section(chunk),
        "page_range": _chunk_page_range(chunk),
        "material_type": material_type or _reference_material_type(chunk),
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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("\\mathrm", "").replace("{", "").replace("}", ""))
