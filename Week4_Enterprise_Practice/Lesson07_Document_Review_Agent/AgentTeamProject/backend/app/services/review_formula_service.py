"""Programmatic formula checks for configured review items."""

from __future__ import annotations

import re
from typing import Any


def execute_formula_checks(formula_checks: list[dict[str, Any]], facts: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [item for item in formula_checks if isinstance(item, dict)]
    results = [_execute_single_formula_check(check, facts) for check in checks]
    return {
        "source": "formula_checks",
        "check_count": len(results),
        "pass_count": sum(1 for item in results if item["status"] == "pass"),
        "fail_count": sum(1 for item in results if item["status"] == "fail"),
        "missing_count": sum(1 for item in results if item["status"] == "missing"),
        "checks": results,
    }


def _execute_single_formula_check(check: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    check_id = str(check.get("id") or check.get("formula_check_id") or "unnamed_formula_check")
    label = str(check.get("label") or check_id)
    unit = _target_unit(check)
    left_fields = _string_list(check.get("left_fields"))
    right_fields = _string_list(check.get("right_fields"))
    config_errors = _formula_config_errors(left_fields, right_fields, unit)
    required_fields = [*left_fields, *right_fields]
    resolved = {field: _field_value(field, facts, unit) for field in _unique(required_fields)}
    field_values = {field: result["value"] for field, result in resolved.items()}
    skipped_candidates = {
        field: result["skipped_candidates"]
        for field, result in resolved.items()
        if result["skipped_candidates"]
    }
    missing_fields = [field for field, value in field_values.items() if value is None]
    tolerance = _absolute_tolerance(check)

    if config_errors:
        status = "unsupported"
        left_value = None
        right_value = None
        difference = None
    elif missing_fields:
        status = "missing"
        left_value = None
        right_value = None
        difference = None
    else:
        left_value = round(sum(field_values[field]["normalized_value"] for field in left_fields), 6)
        right_value = round(sum(field_values[field]["normalized_value"] for field in right_fields), 6)
        difference = round(left_value - right_value, 6)
        status = "pass" if abs(difference) <= tolerance else "fail"

    return {
        "formula_check_id": check_id,
        "label": label,
        "status": status,
        "left_fields": left_fields,
        "right_fields": right_fields,
        "left_value": left_value,
        "right_value": right_value,
        "difference": difference,
        "tolerance": tolerance,
        "unit": unit,
        "config_errors": config_errors,
        "missing_fields": missing_fields,
        "field_values": {field: value for field, value in field_values.items() if value is not None},
        "skipped_candidates": skipped_candidates,
        "required": check.get("required") is True,
    }


def _formula_config_errors(left_fields: list[str], right_fields: list[str], unit: str) -> list[str]:
    errors: list[str] = []
    if not left_fields:
        errors.append("left_fields_empty")
    if not right_fields:
        errors.append("right_fields_empty")
    if _duplicates([*left_fields, *right_fields]):
        errors.append("duplicate_fields")
    if not _is_supported_unit(unit):
        errors.append("unsupported_target_unit")
    return errors


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _field_value(field_name: str, facts: list[dict[str, Any]], unit: str) -> dict[str, Any]:
    candidates = [fact for fact in facts if str(fact.get("field_name") or "") == field_name]
    candidates.sort(key=lambda fact: int(fact.get("confidence") or 0), reverse=True)
    skipped_candidates: list[dict[str, Any]] = []
    for fact in candidates:
        value = _numeric_value(fact)
        source_unit = str(fact.get("unit") or "")
        factor = _unit_factor(source_unit, unit)
        if value is None:
            skipped_candidates.append(_skipped_candidate(fact, "invalid_numeric_value"))
            continue
        if not source_unit.strip():
            skipped_candidates.append(_skipped_candidate(fact, "missing_unit"))
            continue
        if factor is None:
            skipped_candidates.append(_skipped_candidate(fact, "unsupported_unit"))
            continue
        return {
            "value": {
                "fact_id": fact.get("fact_id"),
                "field_name": field_name,
                "value": fact.get("value"),
                "source_unit": fact.get("unit"),
                "normalized_value": round(value * factor, 6),
                "unit": unit,
                "chunk_id": fact.get("chunk_id"),
                "page_range": fact.get("page_range", []),
                "source_text": fact.get("source_text"),
                "confidence": fact.get("confidence"),
            },
            "skipped_candidates": skipped_candidates,
        }
    return {"value": None, "skipped_candidates": skipped_candidates}


def _skipped_candidate(fact: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "fact_id": fact.get("fact_id"),
        "field_name": fact.get("field_name"),
        "value": fact.get("value"),
        "unit": fact.get("unit"),
        "reason": reason,
        "confidence": fact.get("confidence"),
    }


def _target_unit(check: dict[str, Any]) -> str:
    tolerance = check.get("tolerance")
    if isinstance(tolerance, dict) and str(tolerance.get("unit") or "").strip():
        return _canonical_unit(str(tolerance["unit"]))
    return _canonical_unit(str(check.get("unit") or "万m3"))


def _absolute_tolerance(check: dict[str, Any]) -> float:
    tolerance = check.get("tolerance")
    if isinstance(tolerance, dict):
        try:
            return abs(float(tolerance.get("absolute", 0.0)))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _numeric_value(fact: dict[str, Any]) -> float | None:
    for key in ("normalized_value", "value"):
        value = fact.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                return float(match.group(0))
    return None


def _unit_factor(source_unit: str, target_unit: str) -> float | None:
    source = _canonical_unit(source_unit)
    target = _canonical_unit(target_unit)
    if not _is_supported_unit(source) or not _is_supported_unit(target):
        return None
    if source == target:
        return 1.0
    volume_to_wan_m3 = {
        "万m3": 1.0,
        "m3": 0.0001,
    }
    area_to_hm2 = {
        "hm2": 1.0,
        "m2": 0.0001,
    }
    if source in volume_to_wan_m3 and target == "万m3":
        return volume_to_wan_m3[source]
    if source in area_to_hm2 and target == "hm2":
        return area_to_hm2[source]
    return None


def _canonical_unit(unit: str) -> str:
    text = str(unit or "").strip().lower()
    text = text.replace("³", "3").replace("²", "2").replace("^3", "3").replace("^2", "2")
    if not text:
        return ""
    if text in {"万m3", "万方"}:
        return "万m3"
    if text in {"m3", "方"}:
        return "m3"
    if text == "hm2":
        return "hm2"
    if text == "m2":
        return "m2"
    return text


def _is_supported_unit(unit: str) -> bool:
    return _canonical_unit(unit) in {"万m3", "m3", "hm2", "m2"}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
