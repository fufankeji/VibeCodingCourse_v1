"""Normalize expert natural-language review briefs into check item payloads."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


_CLAUSE_SPLIT_RE = re.compile(r"[\n\r；;。!！?？]+|(?<!\d)\.(?!\d)")
_PHRASE_SPLIT_RE = re.compile(r"[\n\r,，；;。.!！?？、:：()（）【】\[\]{}《》<>\"“”'‘’\s]+")

_DOMAIN_TERMS = [
    "项目总投资",
    "土石方",
    "工程占地",
    "植物措施",
    "临时措施",
    "挖方",
    "借方",
    "填方",
    "弃方",
    "表土",
    "水土保持",
    "防治责任范围",
    "扰动面积",
    "占地面积",
    "工程量",
    "排水沟",
    "沉沙池",
    "截水沟",
    "乔木",
    "灌木",
    "草种",
]

_TERM_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{0,6}(?:总投资|土石方|工程占地|植物措施|临时措施|挖方|借方|填方|弃方|表土|"
    r"水土保持|防治责任范围|扰动面积|占地面积|工程量|排水沟|沉沙池|截水沟|乔木|灌木|草种)"
    r"[\u4e00-\u9fff]{0,4}"
)


def normalize_expert_brief_payload(data: dict[str, Any], explicit_fields: set[str] | None = None) -> dict[str, Any]:
    """Return a check-item payload enriched from ``expert_brief`` when present."""
    if not isinstance(data, dict):
        return {}
    expert_brief = data.get("expert_brief")
    if not isinstance(expert_brief, dict):
        return data

    normalized = deepcopy(data)
    explicit_fields = explicit_fields or set()
    brief = {key: value for key, value in expert_brief.items()}
    item_name = _text(brief.get("item_name"))
    objective = _text(brief.get("review_objective"))
    evidence_instruction = _text(brief.get("evidence_instruction"))
    judgement_basis = _text(brief.get("judgement_basis"))
    pass_condition = _text(brief.get("pass_condition"))
    issue_condition = _text(brief.get("issue_condition"))
    regulation_text = _text(brief.get("regulation_text"))

    if item_name and "review_sub_type" not in explicit_fields:
        normalized["review_sub_type"] = item_name
    if pass_condition and "expected_result" not in explicit_fields:
        normalized["expected_result"] = pass_condition
    if issue_condition and "failure_conditions" not in explicit_fields:
        normalized["failure_conditions"] = _merge_unique(
            _string_list(normalized.get("failure_conditions")),
            _split_clauses(issue_condition),
        )

    if "review_criteria" not in explicit_fields:
        normalized["review_criteria"] = _join_criteria(
            normalized.get("review_criteria"),
            judgement_basis=judgement_basis,
            objective=objective,
            evidence_instruction=evidence_instruction,
        )
    if "regulation_clauses" not in explicit_fields:
        normalized["regulation_clauses"] = _merge_unique(
            _string_list(normalized.get("regulation_clauses")),
            _split_clauses(regulation_text),
        )
    if "evidence_scope" not in explicit_fields:
        normalized["evidence_scope"] = _merge_evidence_scope(
            normalized.get("evidence_scope"),
            _infer_evidence_scope(evidence_instruction),
        )
    if "target_fields" not in explicit_fields:
        normalized["target_fields"] = _merge_unique(
            _string_list(normalized.get("target_fields")),
            _extract_target_fields(" ".join([objective, pass_condition, issue_condition])),
        )
    normalized["source_rule_snapshot"] = _merge_source_snapshot(
        normalized.get("source_rule_snapshot"),
        brief,
    )
    return normalized


def meaningful_explicit_fields(data: dict[str, Any]) -> set[str]:
    """Return fields whose submitted values should override expert brief derivation."""
    if not isinstance(data, dict):
        return set()
    return {key for key, value in data.items() if _is_meaningful_explicit_value(value)}


def _is_meaningful_explicit_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_is_meaningful_explicit_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_is_meaningful_explicit_value(item) for item in value)
    return True


def _join_criteria(
    current: Any,
    *,
    judgement_basis: str,
    objective: str,
    evidence_instruction: str,
) -> str:
    parts = _split_existing_criteria(_text(current))
    labelled_parts = [
        ("审查目标", objective),
        ("证据说明", evidence_instruction),
        ("判断依据", judgement_basis),
    ]
    for label, value in labelled_parts:
        if value:
            parts.append(f"{label}：{value}")
    return "\n".join(_merge_unique([], parts))


def _split_existing_criteria(value: str) -> list[str]:
    return [part.strip() for part in value.splitlines() if part.strip()]


def _infer_evidence_scope(instruction: str) -> dict[str, Any]:
    if not instruction:
        return {}
    scope: dict[str, Any] = {"instructions": instruction}
    if any(keyword in instruction for keyword in ["章节", "节"]):
        scope["sections"] = [instruction]
    if "章" in instruction:
        scope["chapters"] = [instruction]
    if any(keyword in instruction for keyword in ["表", "表格"]):
        scope["tables"] = [instruction]
    if "附件" in instruction:
        scope["attachments"] = [instruction]
    if any(keyword in instruction for keyword in ["法规", "规范", "条款"]):
        scope["regulations"] = [instruction]
    return scope


def _merge_evidence_scope(current: Any, inferred: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(current) if isinstance(current, dict) else {}
    for key, value in inferred.items():
        if key == "instructions":
            existing = _text(result.get(key))
            result[key] = "\n".join(_merge_unique([], [existing, _text(value)]))
            continue
        result[key] = _merge_unique(_string_list(result.get(key)), _string_list(value))
    return result


def _extract_target_fields(text: str) -> list[str]:
    fields: list[str] = []
    for term in _DOMAIN_TERMS:
        if term in text:
            fields.append(term)
    for match in _TERM_PATTERN.findall(text):
        token = _trim_term(match)
        if token:
            fields.append(token)
    for token in _PHRASE_SPLIT_RE.split(text):
        token = token.strip()
        if _looks_like_target(token):
            fields.append(token)
    return _merge_unique([], fields)


def _trim_term(value: str) -> str:
    token = value.strip(" ，。；;、:：的是否有无与及和应需核查审查说明一致")
    for term in _DOMAIN_TERMS:
        if term in token:
            return term
    return token if 2 <= len(token) <= 12 else ""


def _looks_like_target(token: str) -> bool:
    if not 2 <= len(token) <= 12:
        return False
    return any(term in token for term in _DOMAIN_TERMS)


def _merge_source_snapshot(current: Any, expert_brief: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if isinstance(current, dict) and _text(current.get("ai_or_human_source")):
        snapshot["ai_or_human_source"] = _text(current.get("ai_or_human_source"))
    snapshot["expert_brief"] = deepcopy(expert_brief)
    snapshot["normalized_from_expert_brief"] = True
    return snapshot


def _split_clauses(value: str) -> list[str]:
    if not value:
        return []
    return _merge_unique([], [part.strip(" \t-—、") for part in _CLAUSE_SPLIT_RE.split(value)])


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for text in (_text(item) for item in value) if text]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.splitlines() if part.strip()]
    return []


def _merge_unique(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            text = _text(value)
            if text and text not in seen:
                result.append(text)
                seen.add(text)
    return result


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
