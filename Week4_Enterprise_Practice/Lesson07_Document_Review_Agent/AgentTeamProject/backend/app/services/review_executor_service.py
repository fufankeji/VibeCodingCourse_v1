"""Lightweight executor registry for configured review check items.

Executor types are user-editable configuration data.  This module only defines
the built-in handler layer and safely falls back when a configured executor id
does not have a first-class handler yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


ExecutorHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def execute_check_item_precheck(
    check_item: dict[str, Any],
    evidence_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a deterministic precheck for one configured review item."""
    if not isinstance(check_item, dict):
        check_item = {}
    if not isinstance(evidence_bundle, dict):
        evidence_bundle = {}

    executor_type_id = str(check_item.get("executor_type_id") or "manual_basic")
    handler_id = executor_type_id if executor_type_id in HANDLER_REGISTRY else "manual_basic"
    base = _base_result(check_item, executor_type_id, handler_id)

    if check_item.get("enabled") is False:
        return {
            **base,
            "execution_status": "disabled",
            "checks": [
                {
                    "type": "executor_disabled",
                    "status": "disabled",
                    "reason": "该配置审查项已停用，不参与自动预检查或问题统计。",
                }
            ],
            "llm_required": False,
            "next_action": "如需执行该审查项，请先启用配置。",
            "summary": "配置审查项已停用。",
        }

    handler = HANDLER_REGISTRY[handler_id]
    return {**base, **handler(check_item, evidence_bundle)}


def _manual_basic_handler(check_item: dict[str, Any], evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_status": "pending",
        "checks": [
            {
                "type": "manual_review_required",
                "status": "pending",
                "reason": "当前执行类型未绑定自动判定逻辑，需要人工或 LLM 结合证据完成审查。",
            }
        ],
        "llm_required": True,
        "next_action": "收集证据后进入人工/LLM 复核。",
        "summary": "已创建基础执行入口，等待复核。",
    }


def _evidence_presence_handler(check_item: dict[str, Any], evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    evidence_scope = _normalize_mapping(check_item.get("evidence_scope"))
    evidence_texts = _evidence_texts(evidence_bundle)
    target_fields = _string_list(check_item.get("target_fields"))
    scope_configured = any(evidence_scope.values())
    has_evidence_text = any(text.strip() for text in evidence_texts)

    checks = [
        {
            "type": "evidence_scope_configured",
            "status": "pass" if scope_configured else "needs_review",
            "reason": "已配置证据范围。" if scope_configured else "未配置证据范围，无法确认应检章节、表格、附件或法规依据。",
        },
        {
            "type": "evidence_text_presence",
            "status": "pass" if has_evidence_text else "needs_review",
            "reason": "已提供待核验证据文本。" if has_evidence_text else "未提供 evidence_texts，无法执行证据存在性核验。",
            "evidence_text_count": len(evidence_texts),
        },
    ]

    if target_fields:
        evidence_blob = "\n".join(evidence_texts)
        matched = [field for field in target_fields if field in evidence_blob]
        missing = [field for field in target_fields if field not in evidence_blob]
        checks.append(
            {
                "type": "target_field_presence",
                "status": "pass" if has_evidence_text and not missing else "needs_review",
                "reason": "目标字段均已在证据文本中出现。" if has_evidence_text and not missing else "部分或全部目标字段未在证据文本中出现。",
                "matched_fields": matched,
                "missing_fields": missing,
            }
        )

    execution_status = "pass" if all(check["status"] == "pass" for check in checks) else "needs_review"
    return {
        "execution_status": execution_status,
        "checks": checks,
        "llm_required": execution_status != "pass",
        "next_action": "证据存在性已满足，可进入结论复核。" if execution_status == "pass" else "补充证据范围或证据文本后再判定。",
        "summary": "完成证据存在性预检查。" if execution_status == "pass" else "证据存在性预检查仍需补充信息。",
    }


def _cross_reference_handler(check_item: dict[str, Any], evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    findings = evidence_bundle.get("cross_reference_findings")
    if not isinstance(findings, list):
        findings = []
    evidence_texts = _evidence_texts(evidence_bundle)
    has_cross_evidence = len(evidence_texts) >= 2 or bool(findings)
    project_comparison = evidence_bundle.get("project_composition_consistency")
    checks = [
        {
            "type": "cross_reference_evidence",
            "status": "needs_review" if has_cross_evidence else "pending",
            "reason": "已发现跨章节/跨表证据，需要进一步判断口径是否一致。" if has_cross_evidence else "尚未提供足够跨章节证据，等待证据定位。",
            "evidence_text_count": len(evidence_texts),
            "finding_count": len(findings),
        }
    ]
    if isinstance(project_comparison, dict):
        comparison_status = str(project_comparison.get("status") or "needs_review")
        checks.append(
            {
                "type": "project_composition_consistency",
                "status": "pass" if comparison_status == "match" else "needs_review",
                "reason": str(project_comparison.get("reason") or "项目组成一致性需复核。"),
                "comparison_status": comparison_status,
            }
        )
    return {
        "execution_status": "needs_review",
        "checks": checks,
        "project_composition_consistency": project_comparison if isinstance(project_comparison, dict) else None,
        "llm_required": True,
        "next_action": "对跨章节字段、表格和附件进行一致性复核。",
        "summary": "跨章节引用核验需要人工/LLM 进一步判断。",
    }


def _base_result(check_item: dict[str, Any], executor_type_id: str, handler_id: str) -> dict[str, Any]:
    return {
        "executor_type_id": executor_type_id,
        "handler_id": handler_id,
        "execution_status": "pending",
        "checks": [],
        "evidence_scope": _normalize_mapping(check_item.get("evidence_scope")),
        "target_fields": _string_list(check_item.get("target_fields")),
        "regulation_clauses": _string_list(check_item.get("regulation_clauses")),
        "llm_required": True,
        "next_action": "等待执行。",
        "summary": "待执行审查预检查。",
    }


def _normalize_mapping(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _string_list(raw) for key, raw in value.items()}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.splitlines() if part.strip()]
    return []


def _evidence_texts(evidence_bundle: dict[str, Any]) -> list[str]:
    direct_texts = _string_list(evidence_bundle.get("evidence_texts"))
    if direct_texts:
        return direct_texts

    texts: list[str] = []
    for key in ("evidence", "matches", "documents"):
        entries = evidence_bundle.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                for field in ("document", "text", "content", "clause_text"):
                    text = str(entry.get(field) or "").strip()
                    if text:
                        texts.append(text)
                        break
            elif str(entry).strip():
                texts.append(str(entry).strip())
    return texts


HANDLER_REGISTRY: dict[str, ExecutorHandler] = {
    "manual_basic": _manual_basic_handler,
    "evidence_presence": _evidence_presence_handler,
    "cross_reference": _cross_reference_handler,
}
