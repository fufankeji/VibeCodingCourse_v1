"""Review issue and ReviewResult assembly helpers."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.services.water_review_evidence import (
    _block_ids_from_matches,
    _evidence_matches_from_chunk,
    _evidence_text_from_matches,
    _source_bbox_list_from_matches,
    _source_pages_from_matches,
)
from app.services.water_review_models import ReviewChunk

def _review_reasoning_summary(
    actual: str,
    expected: str,
    extra_reasoning: dict[str, Any] | None,
    issue_desc: str,
) -> str:
    steps = []
    if isinstance(extra_reasoning, dict):
        steps = [str(item).strip() for item in extra_reasoning.get("judgement_steps", []) if str(item).strip()]
    if steps:
        return "；".join(steps[:6])
    return "；".join(
        item
        for item in [
            f"判定对象：{issue_desc}",
            f"实际命中：{actual}",
            f"规则要求：{expected}",
            "判定结论：存在未命中或待核验证据时，不判定为通过。",
        ]
        if item
    )


def _review_result(
    *,
    issue_id: str,
    session_status: str,
    review_topic: str,
    review_item: str,
    rule_id: str,
    rule_name: str,
    risk_level: str,
    issue_desc: str,
    evidence_matches: list[dict[str, Any]],
    source_bbox_list: list[dict[str, Any]],
    source_pages: list[int],
    reasoning_summary: str,
    fix_suggestion: str,
    confidence: int,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "review_topic": review_topic,
        "review_item": review_item,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "risk_level": risk_level,
        "issue_desc": issue_desc,
        "evidence_text": _evidence_text_from_matches(evidence_matches),
        "evidence_nodes": [
            {
                "chunk_id": match.get("chunk_id"),
                "page": match.get("page") or match.get("primary_page"),
                "page_end": match.get("page_end"),
                "section": match.get("section"),
                "block_ids": match.get("block_ids") or [],
                "bbox_count": match.get("bbox_count") or len(match.get("anchors", [])),
                "matched_terms": match.get("matched_terms") or [],
                "retrieval_sources": match.get("retrieval_sources") or [],
                "text": str(match.get("text") or "")[:800],
            }
            for match in evidence_matches
        ],
        "source_pages": source_pages,
        "source_bbox_list": source_bbox_list,
        "reasoning_summary": reasoning_summary,
        "fix_suggestion": fix_suggestion,
        "confidence": confidence,
        "review_status": session_status,
    }
def _issue(
    session_id: str,
    rule: dict[str, Any],
    issue_desc: str,
    evidence_text: str,
    actual: str,
    expected: str,
    chunk: ReviewChunk | None,
    risk_override: str | None = None,
    confidence: int = 78,
    extra_reasoning: dict[str, Any] | None = None,
    evidence_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue_id = str(uuid.uuid4())
    page = chunk.page_range[0] if chunk else 1
    evidence = evidence_text or (chunk.text[:500] if chunk else "")
    matches = evidence_matches or _evidence_matches_from_chunk(chunk)
    source_bbox_list = _source_bbox_list_from_matches(matches) or (chunk.bbox_list if chunk else [])
    evidence_nodes = _block_ids_from_matches(matches) or [item.get("block_id") for item in (chunk.bbox_list if chunk else []) if item.get("block_id")]
    source_pages = _source_pages_from_matches(matches) or ([page] if page else [])
    risk_level = risk_override or rule["severity"]
    review_status = "待审核"
    fix_suggestion = _suggestion_for(rule)
    reasoning_summary = _review_reasoning_summary(actual, expected, extra_reasoning, issue_desc)
    reasoning = {
        "issue_type": rule["rule_category"],
        "rule_id": rule["rule_id"],
        "rule_name": rule["rule_name"],
        "actual_value": actual,
        "expected_value": expected,
        "evidence_nodes": evidence_nodes,
        "source_pages": source_pages,
        "source_bbox_list": source_bbox_list,
        "review_status": "pending",
        "conclusion_type": "issue" if risk_level != "LOW" else "attention",
        "reasoning_summary": reasoning_summary,
    }
    if isinstance(extra_reasoning, dict):
        reasoning.update(extra_reasoning)
    reasoning["review_result"] = _review_result(
        issue_id=issue_id,
        session_status=review_status,
        review_topic=str(rule.get("rule_category") or ""),
        review_item=str(rule.get("rule_name") or ""),
        rule_id=str(rule.get("rule_id") or ""),
        rule_name=str(rule.get("rule_name") or ""),
        risk_level=str(risk_level),
        issue_desc=issue_desc,
        evidence_matches=matches,
        source_bbox_list=source_bbox_list,
        source_pages=source_pages,
        reasoning_summary=reasoning_summary,
        fix_suggestion=fix_suggestion,
        confidence=confidence,
    )
    return {
        "id": issue_id,
        "session_id": session_id,
        "clause_text": evidence,
        "page_number": page,
        "paragraph_index": 0,
        "highlight_anchor": chunk.chunk_id if chunk else f"page{page}",
        "char_offset_start": chunk.char_start if chunk else 0,
        "char_offset_end": chunk.char_end if chunk else len(evidence),
        "risk_level": risk_level,
        "confidence_score": confidence,
        "source_type": "rule_engine",
        "risk_category": rule["rule_category"],
        "ai_finding": issue_desc,
        "ai_reasoning": json.dumps(reasoning, ensure_ascii=False),
        "suggested_revision": fix_suggestion,
        "human_decision": "pending",
    }


def _suggestion_for(rule: dict[str, Any]) -> str:
    suggestions = {
        "SWC-FORM-001": "补充缺失章节，或在目录及正文中明确对应章节名称与内容。",
        "SWC-FIELD-001": "在项目概况中补充项目名称、建设单位、建设地点、建设性质等基础信息。",
        "SWC-TECH-001": "补充扰动地表面积、防治责任范围面积及对应计算依据。",
        "SWC-TECH-002": "复核土石方平衡表，统一挖方、填方、借方、弃方口径并说明去向。",
        "SWC-TECH-003": "补充表土剥离、临时保存、防护和回覆利用措施。",
        "SWC-TECH-004": "补充弃渣场位置、容量、拦挡排水措施，或说明弃方合法去向。",
        "SWC-ATTR-001": "补充项目区水土流失重点防治区属性及适用规范依据。",
    }
    return suggestions.get(rule["rule_id"], "请补充材料并由审查人员复核。")
