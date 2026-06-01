"""Deterministic completeness checks for earthwork review facts."""

from __future__ import annotations

import re
from typing import Any


def execute_earthwork_audit(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_field = _best_facts(facts)
    checks = [
        _borrow_source_check(by_field),
        _spoil_destination_check(by_field),
        _allocation_explanation_check(by_field),
        _topsoil_chain_check(by_field),
    ]
    checks = [check for check in checks if check is not None]
    status = "pass"
    if any(check["status"] == "missing" for check in checks):
        status = "needs_evidence"
    return {
        "source": "earthwork_audit",
        "status": status,
        "check_count": len(checks),
        "missing_count": sum(1 for check in checks if check["status"] == "missing"),
        "checks": checks,
    }


def _borrow_source_check(by_field: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    borrow = _number(by_field.get("borrow_volume"))
    if borrow is None or borrow <= 0:
        return None
    has_source = _has_text(by_field, ["borrow_area", "borrow_source"])
    return _check(
        "borrow_source",
        "借方来源",
        "pass" if has_source else "missing",
        ["borrow_area"] if not has_source else [],
        [by_field.get("borrow_volume"), by_field.get("borrow_area")],
    )


def _spoil_destination_check(by_field: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    spoil = _number(by_field.get("spoil_volume"))
    if spoil is None or spoil <= 0:
        return None
    has_destination = _has_text(by_field, ["spoil_destination", "spoil_area", "comprehensive_utilization"])
    return _check(
        "spoil_destination",
        "弃方去向",
        "pass" if has_destination else "missing",
        ["spoil_destination"] if not has_destination else [],
        [by_field.get("spoil_volume"), by_field.get("spoil_destination"), by_field.get("spoil_area")],
    )


def _allocation_explanation_check(by_field: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    has_any_volume = any(_number(by_field.get(field)) is not None for field in ["excavation_volume", "fill_volume", "borrow_volume", "spoil_volume"])
    if not has_any_volume:
        return None
    has_explanation = _has_text(by_field, ["comprehensive_utilization", "spoil_destination", "borrow_area", "temp_soil_stockpile"])
    return _check(
        "allocation_explanation",
        "调配说明",
        "pass" if has_explanation else "missing",
        ["comprehensive_utilization"] if not has_explanation else [],
        [by_field.get("comprehensive_utilization"), by_field.get("spoil_destination"), by_field.get("borrow_area")],
    )


def _topsoil_chain_check(by_field: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    has_land_context = _has_text(by_field, ["land_area", "disturbed_area", "prevention_responsibility_area"])
    topsoil_fields = ["topsoil_stripping", "topsoil_preservation", "topsoil_backfill"]
    present = [field for field in topsoil_fields if _has_text(by_field, [field])]
    if not has_land_context and not present:
        return None
    missing = [field for field in topsoil_fields if field not in present]
    return _check(
        "topsoil_standalone_chain",
        "表土单独平衡链条",
        "pass" if not missing else "missing",
        missing,
        [by_field.get(field) for field in topsoil_fields],
    )


def _check(
    audit_check_id: str,
    label: str,
    status: str,
    missing_fields: list[str],
    source_facts: list[dict[str, Any] | None],
) -> dict[str, Any]:
    facts = [fact for fact in source_facts if isinstance(fact, dict)]
    return {
        "audit_check_id": audit_check_id,
        "label": label,
        "status": status,
        "missing_fields": missing_fields,
        "source_fact_ids": [str(fact.get("fact_id") or "") for fact in facts if fact.get("fact_id")],
        "source_chunks": [str(fact.get("chunk_id") or "") for fact in facts if fact.get("chunk_id")],
    }


def _best_facts(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_field: dict[str, dict[str, Any]] = {}
    for fact in sorted([item for item in facts if isinstance(item, dict)], key=lambda item: int(item.get("confidence") or 0), reverse=True):
        field_name = str(fact.get("field_name") or "")
        if field_name and field_name not in by_field:
            by_field[field_name] = fact
    return by_field


def _has_text(by_field: dict[str, dict[str, Any]], field_names: list[str]) -> bool:
    return any(str((by_field.get(field) or {}).get("value") or "").strip() for field in field_names)


def _number(fact: dict[str, Any] | None) -> float | None:
    if not fact:
        return None
    for key in ("normalized_value", "value"):
        value = fact.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                return float(match.group(0))
    return None
