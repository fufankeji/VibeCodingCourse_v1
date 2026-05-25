"""Editable SCMC review configuration.

This is the first configuration layer above the static SCMC topics.  Review
items and executor types are intentionally data, not hard-coded Python classes,
so reviewers can add/remove/update topic-specific review behavior incrementally.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.review_item import ReviewItem
from app.services import review_agent_service
from app.services.review_brief_service import meaningful_explicit_fields, normalize_expert_brief_payload
from app.services.review_executor_service import execute_check_item_precheck
from app.services.review_rule_schema import SCMC_TOPIC_SPECS


CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "scmc_review_config.json"
_CONFIG_LOCK = threading.RLock()


DEFAULT_EXECUTOR_TYPES = [
    {
        "id": "manual_basic",
        "label": "人工基础核验",
        "description": "基础审查执行类型：定位证据、记录结论，由人工或 LLM 辅助判断。",
        "enabled": True,
    },
    {
        "id": "evidence_presence",
        "label": "证据存在性核验",
        "description": "检查章节、表格、附件或法规依据是否存在。",
        "enabled": True,
    },
    {
        "id": "cross_reference",
        "label": "跨章节引用核验",
        "description": "检查同一指标在章节、表格、附件之间是否互相支撑。",
        "enabled": True,
    },
]

_EXPERT_BRIEF_DERIVED_FIELDS = {
    "review_sub_type",
    "expected_result",
    "failure_conditions",
    "review_criteria",
    "regulation_clauses",
    "evidence_scope",
    "target_fields",
}


def load_review_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        if not CONFIG_PATH.exists():
            config = _default_config()
            save_review_config(config)
            return config
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid review config JSON: {CONFIG_PATH}") from exc
        return _normalize_config(data)


def _read_review_config_without_side_effects() -> dict[str, Any]:
    with _CONFIG_LOCK:
        if not CONFIG_PATH.exists():
            return _normalize_config(_default_config())
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid review config JSON: {CONFIG_PATH}") from exc
        return _normalize_config(data)


def save_review_config(config: dict[str, Any]) -> dict[str, Any]:
    with _CONFIG_LOCK:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        normalized = _normalize_config(config)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=CONFIG_PATH.parent,
                prefix=f".{CONFIG_PATH.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(payload)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, CONFIG_PATH)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return normalized


def list_executor_types() -> list[dict[str, Any]]:
    with _CONFIG_LOCK:
        return load_review_config()["executor_types"]


def create_executor_type(data: dict[str, Any]) -> dict[str, Any]:
    with _CONFIG_LOCK:
        config = load_review_config()
        item = {
            "id": _safe_id(data.get("id") or f"executor-{uuid.uuid4().hex[:8]}"),
            "label": str(data.get("label") or "未命名执行类型"),
            "description": str(data.get("description") or ""),
            "enabled": _parse_bool(data.get("enabled", True)),
        }
        if any(existing["id"] == item["id"] for existing in config["executor_types"]):
            raise ValueError(f"Executor type already exists: {item['id']}")
        config["executor_types"].append(item)
        save_review_config(config)
        return item


def update_executor_type(executor_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _CONFIG_LOCK:
        config = load_review_config()
        for item in config["executor_types"]:
            if item["id"] == executor_id:
                if "label" in patch:
                    item["label"] = str(patch["label"] or item["label"])
                if "description" in patch:
                    item["description"] = str(patch["description"] or "")
                if "enabled" in patch:
                    enabled = _parse_bool(patch["enabled"])
                    if not enabled:
                        _ensure_executor_can_be_disabled(executor_id, config["check_items"])
                    item["enabled"] = enabled
                save_review_config(config)
                return item
        raise KeyError(executor_id)


def delete_executor_type(executor_id: str) -> None:
    with _CONFIG_LOCK:
        if executor_id == "manual_basic":
            raise ValueError("manual_basic executor type cannot be deleted")
        config = load_review_config()
        if not any(item["id"] == executor_id for item in config["executor_types"]):
            raise KeyError(executor_id)
        config["executor_types"] = [item for item in config["executor_types"] if item["id"] != executor_id]
        for check_item in config["check_items"]:
            if check_item.get("executor_type_id") == executor_id:
                check_item["executor_type_id"] = "manual_basic"
                check_item["review_type"] = "人工基础核验"
        save_review_config(config)


def list_check_item_specs(topic_id: str | None = None) -> list[dict[str, Any]]:
    with _CONFIG_LOCK:
        items = load_review_config()["check_items"]
        if topic_id:
            return [item for item in items if item.get("topic_id") == topic_id]
        return items


def create_check_item_spec(data: dict[str, Any]) -> dict[str, Any]:
    with _CONFIG_LOCK:
        config = load_review_config()
        item_data = {
            **data,
            "id": _safe_id(data.get("id") or f"check-{uuid.uuid4().hex[:8]}"),
        }
        item_data = normalize_expert_brief_payload(item_data, explicit_fields=meaningful_explicit_fields(data))
        _validate_check_item_write(item_data, config["executor_types"])
        item = _normalize_check_item(item_data, config["executor_types"])
        if any(existing["id"] == item["id"] for existing in config["check_items"]):
            raise ValueError(f"Check item already exists: {item['id']}")
        config["check_items"].append(item)
        save_review_config(config)
        return item


def update_check_item_spec(item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _CONFIG_LOCK:
        config = load_review_config()
        for index, item in enumerate(config["check_items"]):
            if item["id"] == item_id:
                item_data = {**item, **patch, "id": item_id}
                if "expert_brief" in patch:
                    explicit_fields = meaningful_explicit_fields(patch)
                    item_data = _drop_stale_expert_brief_derivatives(item_data, explicit_fields)
                    item_data = normalize_expert_brief_payload(item_data, explicit_fields=explicit_fields)
                _validate_check_item_write(item_data, config["executor_types"])
                updated = _normalize_check_item(item_data, config["executor_types"])
                config["check_items"][index] = updated
                save_review_config(config)
                return updated
        raise KeyError(item_id)


def delete_check_item_spec(item_id: str) -> None:
    with _CONFIG_LOCK:
        config = load_review_config()
        if not any(item["id"] == item_id for item in config["check_items"]):
            raise KeyError(item_id)
        config["check_items"] = [item for item in config["check_items"] if item["id"] != item_id]
        save_review_config(config)


def preview_check_item_spec(session_id: str, data: dict[str, Any], db: Session) -> dict[str, Any]:
    config = _read_review_config_without_side_effects()
    item_data = {
        **data,
        "id": data.get("id") or "draft-preview",
    }
    item_data = normalize_expert_brief_payload(item_data, explicit_fields=meaningful_explicit_fields(data))
    _validate_check_item_write(item_data, config["executor_types"])
    normalized = _normalize_check_item(item_data, config["executor_types"])
    return review_agent_service.preview_check_item_with_agent(session_id, normalized, db)


def _default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "executor_types": deepcopy(DEFAULT_EXECUTOR_TYPES),
        "check_items": [],
    }


def _drop_stale_expert_brief_derivatives(item: dict[str, Any], explicit_fields: set[str]) -> dict[str, Any]:
    cleaned = deepcopy(item)
    for field in _EXPERT_BRIEF_DERIVED_FIELDS - explicit_fields:
        cleaned.pop(field, None)
    return cleaned


def _normalize_config(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    raw_executor_types = data.get("executor_types")
    executor_types = raw_executor_types if isinstance(raw_executor_types, list) and raw_executor_types else DEFAULT_EXECUTOR_TYPES
    executor_types = [_normalize_executor_type(item) for item in executor_types]
    _ensure_unique_ids(executor_types, "executor type")
    if not any(item["id"] == "manual_basic" for item in executor_types):
        executor_types.insert(0, deepcopy(DEFAULT_EXECUTOR_TYPES[0]))

    raw_check_items = data.get("check_items")
    check_item_source = raw_check_items if isinstance(raw_check_items, list) else []
    check_items = [
        _normalize_check_item(item, executor_types)
        for item in check_item_source
        if isinstance(item, dict)
    ]
    _ensure_unique_ids(check_items, "check item")
    return {
        "version": int(data.get("version") or 1),
        "executor_types": executor_types,
        "check_items": check_items,
    }


def _normalize_executor_type(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    return {
        "id": _safe_id(item.get("id") or f"executor-{uuid.uuid4().hex[:8]}"),
        "label": str(item.get("label") or "未命名执行类型"),
        "description": str(item.get("description") or ""),
        "enabled": _parse_bool(item.get("enabled", True)),
    }


def _normalize_check_item(item: dict[str, Any], executor_types: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    if not executor_types:
        executor_types = [deepcopy(DEFAULT_EXECUTOR_TYPES[0])]
    executor_by_id = {executor["id"]: executor for executor in executor_types}
    executor_id = str(item.get("executor_type_id") or "manual_basic")
    executor = executor_by_id.get(executor_id) or executor_by_id.get("manual_basic") or executor_types[0]
    topic_id = str(item.get("topic_id") or SCMC_TOPIC_SPECS[0]["id"])
    if topic_id not in {spec["id"] for spec in SCMC_TOPIC_SPECS}:
        topic_id = SCMC_TOPIC_SPECS[0]["id"]
    return {
        "id": _safe_id(item.get("id") or f"check-{uuid.uuid4().hex[:8]}"),
        "topic_id": topic_id,
        "rule_id": str(item.get("rule_id") or ""),
        "executor_type_id": executor["id"],
        "review_type": str(item.get("review_type") or executor["label"]),
        "review_sub_type": str(item.get("review_sub_type") or item.get("name") or "未命名审查项"),
        "status": str(item.get("status") or "pending"),
        "conclusion": str(item.get("conclusion") or "待按配置执行审查。"),
        "evidence_scope": item.get("evidence_scope") if isinstance(item.get("evidence_scope"), dict) else {},
        "target_fields": _string_list(item.get("target_fields")),
        "regulation_clauses": _string_list(item.get("regulation_clauses")),
        "review_criteria": str(item.get("review_criteria") or ""),
        "expected_result": str(item.get("expected_result") or ""),
        "failure_conditions": _string_list(item.get("failure_conditions")),
        "source_rule_snapshot": item.get("source_rule_snapshot") if isinstance(item.get("source_rule_snapshot"), dict) else {},
        "enabled": _parse_bool(item.get("enabled", True)),
    }


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text)
    return text.strip("-") or f"id-{uuid.uuid4().hex[:8]}"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.splitlines() if part.strip()]
    return []


def _ensure_unique_ids(items: list[dict[str, Any]], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id") or "")
        if item_id in seen:
            raise ValueError(f"Duplicate {label} id: {item_id}")
        seen.add(item_id)


def _validate_check_item_write(item: dict[str, Any], executor_types: list[dict[str, Any]]) -> None:
    topic_id = str(item.get("topic_id") or SCMC_TOPIC_SPECS[0]["id"])
    if topic_id not in {spec["id"] for spec in SCMC_TOPIC_SPECS}:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    executor_id = str(item.get("executor_type_id") or "manual_basic")
    executor_by_id = {executor["id"]: executor for executor in executor_types}
    if executor_id not in executor_by_id:
        raise ValueError(f"Unknown executor_type_id: {executor_id}")
    if _parse_bool(item.get("enabled", True)) and not _parse_bool(executor_by_id[executor_id].get("enabled", True)):
        raise ValueError(f"Disabled executor_type_id cannot be used by an enabled check item: {executor_id}")


def _build_preview_evidence_bundle(session_id: str, check_item: dict[str, Any], db: Session) -> dict[str, Any]:
    rows = db.query(ReviewItem).filter(ReviewItem.session_id == session_id).all()
    target_fields = _string_list(check_item.get("target_fields"))
    fallback_terms = _fallback_match_terms(check_item)
    scope_terms = _evidence_scope_terms(check_item)
    ranked_rows: list[tuple[int, ReviewItem, set[str], dict[str, Any]]] = []
    matched_fields: set[str] = set()

    for index, row in enumerate(rows):
        reasoning = _safe_json_dict(row.ai_reasoning)
        row_blob = "\n".join([row.clause_text or "", row.ai_finding or "", row.ai_reasoning or ""])
        row_target_matches = {field for field in target_fields if field and field in row_blob}
        row_fallback_matches = {term for term in fallback_terms if term and term in row_blob}
        row_scope_matches = {term for term in scope_terms if term and term in row_blob}
        row_matches = {*row_target_matches, *row_fallback_matches, *row_scope_matches}
        relevance = len(row_target_matches) * 20 + len(row_fallback_matches) * 8
        if row_scope_matches and (row_target_matches or row_fallback_matches):
            relevance += min(len(row_scope_matches), 3)
        if str(check_item.get("rule_id") or "") and str(check_item.get("rule_id") or "") in row_blob:
            relevance += 3
        if str(check_item.get("review_sub_type") or "") and str(check_item.get("review_sub_type") or "") in row_blob:
            relevance += 1
        if relevance > 0:
            matched_fields.update(row_target_matches)
            ranked_rows.append((relevance * 1000 - index, row, row_matches, reasoning))

    ranked_rows.sort(key=lambda item: item[0], reverse=True)
    selected = ranked_rows[:5]
    missing_fields = [field for field in target_fields if field not in matched_fields]
    structured_facts: list[Any] = []
    cross_reference_findings: list[Any] = []
    langextract_grounding: list[Any] = []
    for _, _, _, reasoning in selected:
        _extend_json_list(structured_facts, reasoning.get("structured_facts"))
        _extend_json_list(cross_reference_findings, reasoning.get("cross_chapter_findings"))
        _extend_json_list(cross_reference_findings, reasoning.get("cross_reference_findings"))
        _extend_json_list(langextract_grounding, reasoning.get("langextract_grounding"))

    return {
        "evidence_texts": [_preview_evidence_text(row) for _, row, _, _ in selected],
        "evidence_locations": [_preview_evidence_location(row) for _, row, _, _ in selected],
        "matched_target_fields": [field for field in target_fields if field in matched_fields],
        "missing_target_fields": missing_fields,
        "structured_facts": structured_facts,
        "cross_reference_findings": cross_reference_findings,
        "langextract_grounding": langextract_grounding,
        "source": "session_review_items",
    }


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _preview_evidence_text(row: ReviewItem) -> str:
    parts = [row.clause_text or "", row.ai_finding or ""]
    return "\n".join(part for part in parts if part).strip()


def _preview_evidence_location(row: ReviewItem) -> dict[str, Any]:
    return {
        "review_item_id": row.id,
        "page_number": row.page_number,
        "paragraph_index": row.paragraph_index,
        "highlight_anchor": row.highlight_anchor,
    }


def _fallback_match_terms(check_item: dict[str, Any]) -> list[str]:
    text_parts = [
        check_item.get("review_sub_type"),
        check_item.get("review_criteria"),
        check_item.get("expected_result"),
        *(_string_list(check_item.get("failure_conditions"))),
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for part in text_parts:
        text = str(part or "")
        for token in _split_preview_terms(text):
            if token not in seen:
                terms.append(token)
                seen.add(token)
    return terms


_PREVIEW_TERM_STOPWORDS = {
    "未见",
    "完整",
    "配置",
    "说明",
    "需要",
    "复核",
    "支撑",
    "材料",
    "章节",
    "表格",
    "专家",
    "规则",
    "审查",
    "依据",
    "是否",
    "核验",
    "补充",
    "附件",
    "存在",
    "相关",
}

_PREVIEW_DOMAIN_TERMS = {
    "乔木",
    "灌木",
    "草种",
    "乔灌草",
    "植物措施",
    "临时措施",
    "排水沟",
    "沉沙池",
    "截水沟",
    "专项比选",
    "水土保持",
    "工程量",
}


def _split_preview_terms(text: str) -> list[str]:
    separators = " \t\r\n,，。；;、:：()（）[]【】{}《》<>\"'“”‘’!?！？"
    translated = text
    for separator in separators:
        translated = translated.replace(separator, " ")
    terms: list[str] = []
    for raw in translated.split():
        token = raw.strip()
        if _is_preview_match_term(token):
            terms.append(token)
    return terms


def _is_preview_match_term(token: str) -> bool:
    if not token or token in _PREVIEW_TERM_STOPWORDS:
        return False
    if len(token) >= 4:
        return True
    return any(domain_term in token or token in domain_term for domain_term in _PREVIEW_DOMAIN_TERMS)


def _evidence_scope_terms(check_item: dict[str, Any]) -> list[str]:
    scope = check_item.get("evidence_scope")
    if not isinstance(scope, dict):
        return []
    terms: list[str] = []
    for value in scope.values():
        if isinstance(value, list):
            for item in value:
                terms.extend(_split_preview_terms(str(item or "")))
        elif isinstance(value, str):
            terms.extend(_split_preview_terms(value))
    return _unique_strings(terms)


def _safe_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extend_json_list(target: list[Any], value: Any) -> None:
    if isinstance(value, list):
        target.extend(value)
    elif value:
        target.append(value)


def _preview_review_conclusion(precheck_result: dict[str, Any]) -> dict[str, Any]:
    status = str(precheck_result.get("execution_status") or "pending")
    return {
        "status": status,
        "summary": precheck_result.get("summary") or "",
        "next_action": precheck_result.get("next_action") or "",
        "llm_required": bool(precheck_result.get("llm_required", True)),
    }


def _suggest_preview_rule_improvements(
    check_item: dict[str, Any],
    evidence_bundle: dict[str, Any],
    precheck_result: dict[str, Any],
) -> list[str]:
    suggestions: list[str] = []
    if evidence_bundle.get("missing_target_fields"):
        suggestions.append("补充或调整 target_fields，确认缺失字段是否需要作为强制证据项。")
    if not evidence_bundle.get("evidence_texts"):
        suggestions.append("扩大 evidence_scope 或补充关键词，以便命中会话中的候选证据。")
    if not any(check_item.get("evidence_scope", {}).values()):
        suggestions.append("补充 evidence_scope，明确应核验的章节、表格或附件。")
    if precheck_result.get("llm_required"):
        suggestions.append("为该审查项补充 expected_result 与 failure_conditions，降低后续人工/LLM 判定歧义。")
    return suggestions or ["当前草稿可进入保存前复核，建议专家确认证据范围与结论口径。"]


def _ensure_executor_can_be_disabled(executor_id: str, check_items: list[dict[str, Any]]) -> None:
    referencing_enabled_items = [
        str(item.get("id") or "")
        for item in check_items
        if str(item.get("executor_type_id") or "") == executor_id and _parse_bool(item.get("enabled", True))
    ]
    if referencing_enabled_items:
        ids = ", ".join(item_id for item_id in referencing_enabled_items if item_id)
        raise ValueError(
            f"Cannot disable executor_type_id used by enabled check item: {executor_id}"
            + (f" ({ids})" if ids else "")
        )


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1}:
            return bool(value)
        raise ValueError(f"Invalid boolean value: {value}")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        if normalized == "":
            return default
    raise ValueError(f"Invalid boolean value: {value}")
