"""Rule review and issue assembly for water review."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.services.water_review_extraction import _best_chunk, _to_number
from app.services.water_review_models import QUICK_VALIDATION_ISSUE_COUNT, RULES, ReviewChunk
from app.services.water_review_utils import _detect_sections

def review_rules(
    session_id: str,
    chunks: list[ReviewChunk],
    fields: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
    evidence_store: Any | None = None,
) -> list[dict[str, Any]]:
    text = "\n".join(chunk.text for chunk in chunks)
    by_name = {field["field_name"]: field for field in fields}
    issues: list[dict[str, Any]] = []
    configured_rules = rules or RULES

    found_sections = _detect_sections(text)
    missing_sections = [name for name in ["项目概况", "防治责任范围", "防治措施", "监测", "投资估算", "结论"] if name not in found_sections]
    if missing_sections:
        issues.append(_issue(session_id, RULES[0], "缺少或未能识别必备章节：" + "、".join(missing_sections), "", "已识别章节：" + "、".join(found_sections), RULES[0]["expected"], _best_chunk(chunks, ["目录", "项目概况"])))

    issues.extend(
        _issues_from_configured_rules(
            session_id,
            chunks,
            text,
            fields,
            configured_rules,
            limit=QUICK_VALIDATION_ISSUE_COUNT - len(issues),
            evidence_store=evidence_store,
        )
    )

    missing_basic = [
        label
        for key, label in [
            ("project_name", "项目名称"),
            ("construction_unit", "建设单位"),
            ("construction_location", "建设地点"),
            ("project_nature", "建设性质"),
        ]
        if not by_name[key]["value"]
    ]
    if missing_basic:
        _append_if_room(issues, _issue(session_id, RULES[1], "基础信息缺失或未见明确表述：" + "、".join(missing_basic), "", "缺失字段：" + "、".join(missing_basic), RULES[1]["expected"], _best_chunk(chunks, ["项目概况", "综合说明"])))

    if not by_name["disturbed_area"]["value"]:
        _append_if_room(issues, _issue(session_id, RULES[2], "未见扰动地表面积或防治责任范围面积的明确数值。", "", "材料中未见明确表述", RULES[2]["expected"], _best_chunk(chunks, ["扰动", "防治责任范围", "占地"])))

    excavation = _to_number(by_name["excavation_volume"]["normalized_value"])
    fill = _to_number(by_name["fill_volume"]["normalized_value"])
    borrow = _to_number(by_name["borrow_volume"]["normalized_value"])
    spoil = _to_number(by_name["spoil_volume"]["normalized_value"])
    if all(value is not None for value in [excavation, fill, borrow, spoil]):
        left = excavation + borrow
        right = fill + spoil
        tolerance = max(abs(left), abs(right), 1.0) * 0.05
        if abs(left - right) > tolerance:
            actual = f"挖方+借方={left:g}，填方+弃方={right:g}"
            _append_if_room(issues, _issue(session_id, RULES[3], "土石方平衡关系存在不一致。", "", actual, RULES[3]["expected"], _best_chunk(chunks, ["土石方", "挖方", "填方", "弃方"])))
    elif any(value is not None for value in [excavation, fill, borrow, spoil]):
        _append_if_room(issues, _issue(session_id, RULES[3], "土石方平衡关键字段不完整，无法完成一致性核验。", "", "已抽取部分土石方字段，但缺少挖/填/借/弃中的一项或多项", RULES[3]["expected"], _best_chunk(chunks, ["土石方", "挖方", "填方", "弃方"]), risk_override="MEDIUM"))

    has_disturbance = bool(by_name["disturbed_area"]["value"] or by_name["land_area"]["value"])
    has_topsoil = any(by_name[key]["value"] for key in ["topsoil_stripping", "topsoil_preservation", "topsoil_backfill"])
    if has_disturbance and not has_topsoil:
        _append_if_room(issues, _issue(session_id, RULES[4], "存在扰动或占地信息，但未见表土剥离、保存或回覆措施。", "", "材料中未见明确表土保护措施", RULES[4]["expected"], _best_chunk(chunks, ["表土", "防治措施", "扰动"])))

    if spoil and spoil > 0 and not by_name["spoil_area"]["value"]:
        _append_if_room(issues, _issue(session_id, RULES[5], "存在弃方/弃渣量，但未见弃渣场或弃土去向说明。", "", f"弃方/弃渣量={spoil:g}", RULES[5]["expected"], _best_chunk(chunks, ["弃方", "弃渣", "弃土"])))

    if not by_name["key_prevention_or_control_area"]["value"]:
        _append_if_room(issues, _issue(session_id, RULES[6], "未见项目所在区域属性说明。", "", "材料中未见重点预防区、重点治理区或易发生水土流失区域表述", RULES[6]["expected"], _best_chunk(chunks, ["区域", "水土流失", "项目区"])))

    if not issues:
        summary_chunk = chunks[0] if chunks else None
        issues.append(_issue(session_id, RULES[6], "首版规则未发现高/中风险问题，建议人工抽查关键字段和图表一致性。", "", "自动规则未命中", "人工复核确认", summary_chunk, risk_override="LOW", confidence=55))

    return issues[:QUICK_VALIDATION_ISSUE_COUNT]


def _append_if_room(issues: list[dict[str, Any]], issue: dict[str, Any]) -> None:
    if len(issues) < QUICK_VALIDATION_ISSUE_COUNT:
        issues.append(issue)

def _issues_from_configured_rules(
    session_id: str,
    chunks: list[ReviewChunk],
    full_text: str,
    fields: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    limit: int = 12,
    evidence_store: Any | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if limit <= 0:
        return issues
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        structured_issue = _issue_from_structured_check_item(session_id, chunks, fields, rule, evidence_store)
        if structured_issue:
            issues.append(structured_issue)
            if len(issues) >= limit:
                break
            continue
        target_fields = [str(item) for item in rule.get("target_fields", []) if str(item).strip()]
        if not target_fields:
            continue
        matched = [field for field in target_fields if field in full_text]
        missing = [field for field in target_fields if field not in full_text]
        if not missing:
            continue
        # Keep the first version conservative: only emit rules with at least
        # one adjacent evidence hit, or rules whose target is a known high-frequency item.
        high_frequency = any(key in "、".join(target_fields) for key in ["土石方", "弃方", "表土", "占地", "防治责任范围", "监测", "投资"])
        if not matched and not high_frequency:
            continue
        evidence_matches = _evidence_matches_from_chunks(chunks, matched or target_fields)
        chunk = _chunk_for_evidence_match(chunks, evidence_matches[0]) if evidence_matches else _best_chunk(chunks, matched or target_fields)
        severity = _severity_from_policy(rule.get("severity_policy", ""))
        actual = "已命中：" + "、".join(matched) if matched else "材料中未见明确表述"
        if missing:
            actual += "；待核验：" + "、".join(missing[:6])
        issues.append(
            _issue(
                session_id=session_id,
                rule={
                    "rule_id": rule.get("rule_id", "WSB-CONFIG"),
                    "rule_name": rule.get("rule_name", "规则库审查"),
                    "rule_category": rule.get("category", "规则库审查"),
                    "severity": severity,
                    "expected": rule.get("evidence_requirement", "应满足规则库证据要求"),
                },
                issue_desc=_generic_rule_issue_desc(rule, matched, missing),
                evidence_text="",
                actual=actual,
                expected=rule.get("evidence_requirement", "应满足规则库证据要求"),
                chunk=chunk,
                risk_override=severity,
                confidence=68 if matched else 58,
                extra_reasoning=_generic_rule_reasoning(rule, matched, missing),
                evidence_matches=evidence_matches,
            )
        )
        if len(issues) >= limit:
            break
    return issues


def _issue_from_structured_check_item(
    session_id: str,
    chunks: list[ReviewChunk],
    fields: list[dict[str, Any]],
    rule: dict[str, Any],
    evidence_store: Any | None = None,
) -> dict[str, Any] | None:
    if not isinstance(rule.get("evidence_slots"), list) and not isinstance(rule.get("formula_checks"), list):
        return None

    from app.services.review_agent_service import build_evidence_slot_package
    from app.services.review_formula_service import execute_formula_checks
    from app.services.rag_service import RAGReviewError

    retrieval_trace = {
        "requested_store": evidence_store is not None,
        "used_store": evidence_store is not None,
        "degraded": False,
        "reason_type": "",
    }
    try:
        evidence_slot_package = build_evidence_slot_package(
            rule,
            chunks,
            evidence_store,
            use_bm25=True,
            use_neighbors=True,
            use_rerank=evidence_store is not None,
        )
    except RAGReviewError as exc:
        if evidence_store is None or not _is_vector_retrieval_failure(exc):
            raise
        retrieval_trace = {
            "requested_store": True,
            "used_store": False,
            "degraded": True,
            "reason_type": "vector_retrieval_failed",
        }
        evidence_slot_package = build_evidence_slot_package(
            rule,
            chunks,
            None,
            use_bm25=True,
            use_neighbors=True,
            use_rerank=False,
        )
    formula_check_results = execute_formula_checks(
        [item for item in rule.get("formula_checks", []) if isinstance(item, dict)],
        fields,
    )
    earthwork_audit_results = _earthwork_audit_results(rule, fields)
    from app.services.project_composition_service import analyze_project_composition_consistency

    project_comparison = analyze_project_composition_consistency(chunks, rule)
    project_comparison_status = (
        str(project_comparison.get("status") or "")
        if isinstance(project_comparison, dict)
        else ""
    )
    missing_slot_ids = [
        str(slot_id)
        for slot_id in evidence_slot_package.get("missing_required_slot_ids", [])
        if str(slot_id).strip()
    ]
    formula_checks = [item for item in formula_check_results.get("checks", []) if isinstance(item, dict)]
    failed_formula_ids = [
        str(item.get("formula_check_id") or "")
        for item in formula_checks
        if item.get("status") == "fail"
    ]
    missing_formula_ids = [
        str(item.get("formula_check_id") or "")
        for item in formula_checks
        if item.get("status") in {"missing", "unsupported"}
    ]
    missing_audit_ids = [
        str(item.get("audit_check_id") or "")
        for item in earthwork_audit_results.get("checks", [])
        if isinstance(item, dict) and item.get("status") == "missing"
    ]
    project_comparison_blocks = project_comparison_status in {"mismatch", "needs_review"}
    if (
        not missing_slot_ids
        and not failed_formula_ids
        and not missing_formula_ids
        and not missing_audit_ids
        and not project_comparison_blocks
    ):
        return None

    if missing_slot_ids or missing_formula_ids:
        status = "needs_evidence"
    elif failed_formula_ids or project_comparison_status == "mismatch":
        status = "issue"
    else:
        status = "needs_evidence" if missing_audit_ids or project_comparison_status == "needs_review" else "issue"
    evidence_matches = _evidence_matches_from_slot_package(evidence_slot_package, chunks)
    chunk = _chunk_for_evidence_match(chunks, evidence_matches[0]) if evidence_matches else _best_chunk(chunks, _structured_issue_keywords(rule, evidence_slot_package))
    page = chunk.page_range[0] if chunk else 1
    evidence = chunk.text[:500] if chunk else ""
    rule_name = str(rule.get("rule_name") or rule.get("review_sub_type") or "配置化审查项")
    category = str(rule.get("category") or rule.get("review_type") or "配置化审查")
    expected = str(rule.get("evidence_requirement") or rule.get("expected_result") or "应满足配置化审查要求")
    actual_value, finding_reason = _structured_issue_reason(
        missing_slot_ids,
        missing_formula_ids,
        failed_formula_ids,
        missing_audit_ids,
        project_comparison_status,
        project_comparison,
    )
    issue_id = str(uuid.uuid4())
    source_bbox_list = _source_bbox_list_from_matches(evidence_matches) or (chunk.bbox_list if chunk else [])
    evidence_nodes = _block_ids_from_matches(evidence_matches) or [item.get("block_id") for item in (chunk.bbox_list if chunk else [])]
    source_pages = _source_pages_from_matches(evidence_matches) or ([page] if page else [])
    reasoning_summary = _review_reasoning_summary(actual_value, expected, None, f"{rule_name}：{finding_reason}，需补齐后复核。")
    suggestion = "补齐配置项所需证据或修正文档数据后重新审查。"
    risk_level = _severity_from_policy(str(rule.get("severity_policy") or "")) if status == "issue" else "HIGH"
    reasoning = {
        "issue_type": category,
        "rule_id": str(rule.get("rule_id") or rule.get("id") or "WSB-CONFIG"),
        "rule_name": rule_name,
        "actual_value": actual_value,
        "expected_value": expected,
        "evidence_nodes": evidence_nodes,
        "source_pages": source_pages,
        "source_bbox_list": source_bbox_list,
        "evidence_slot_package": evidence_slot_package,
        "retrieval_trace": retrieval_trace,
        "formula_check_results": formula_check_results,
        "earthwork_audit_results": earthwork_audit_results,
        "project_composition_consistency": project_comparison,
        "review_status": status,
        "conclusion_type": status,
        "reasoning_summary": reasoning_summary,
        "review_result": _review_result(
            issue_id=issue_id,
            session_status="待审核",
            review_topic=category,
            review_item=str(rule.get("review_sub_type") or rule_name),
            rule_id=str(rule.get("rule_id") or rule.get("id") or "WSB-CONFIG"),
            rule_name=rule_name,
            risk_level=risk_level,
            issue_desc=f"{rule_name}：{finding_reason}，需补齐后复核。",
            evidence_matches=evidence_matches or _evidence_matches_from_chunk(chunk),
            source_bbox_list=source_bbox_list,
            source_pages=source_pages,
            reasoning_summary=reasoning_summary,
            fix_suggestion=suggestion,
            confidence=76,
        ),
    }
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
        "confidence_score": 76,
        "source_type": "rule_engine",
        "risk_category": category,
        "ai_finding": f"{rule_name}：{finding_reason}，需补齐后复核。",
        "ai_reasoning": json.dumps(reasoning, ensure_ascii=False),
        "suggested_revision": suggestion,
        "human_decision": "pending",
    }


def _is_vector_retrieval_failure(exc: Exception) -> bool:
    return str(exc).startswith("vector retrieval failed:")


def _earthwork_audit_results(rule: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    if not _should_run_earthwork_audit(rule):
        return {"source": "earthwork_audit", "status": "not_applicable", "check_count": 0, "missing_count": 0, "checks": []}
    from app.services.earthwork_audit_service import execute_earthwork_audit

    return execute_earthwork_audit(fields)


def _should_run_earthwork_audit(rule: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in [
            rule.get("rule_id"),
            rule.get("rule_name"),
            rule.get("review_type"),
            rule.get("review_sub_type"),
            rule.get("category"),
            rule.get("review_criteria"),
            rule.get("expected_result"),
        ]
    )
    if "土石方" in text or "表土" in text:
        return True
    earthwork_fields = {"excavation_volume", "fill_volume", "borrow_volume", "spoil_volume"}
    for check in rule.get("formula_checks", []):
        if not isinstance(check, dict):
            continue
        configured = set(_string_list_for_structured_rule(check.get("left_fields"))) | set(_string_list_for_structured_rule(check.get("right_fields")))
        if configured.intersection(earthwork_fields):
            return True
    return False


def _string_list_for_structured_rule(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _structured_issue_reason(
    missing_slot_ids: list[str],
    missing_formula_ids: list[str],
    failed_formula_ids: list[str],
    missing_audit_ids: list[str],
    project_comparison_status: str = "",
    project_comparison: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if missing_slot_ids:
        return "缺失必填 evidence_slots：" + "、".join(missing_slot_ids), "必填证据槽位缺失"
    if missing_formula_ids:
        return "公式校验缺少必要字段或单位不支持：" + "、".join(item for item in missing_formula_ids if item), "公式校验证据缺失"
    if failed_formula_ids:
        return "公式校验未通过：" + "、".join(item for item in failed_formula_ids if item), "公式校验未通过"
    if missing_audit_ids:
        return "土石方结构化审计缺项：" + "、".join(item for item in missing_audit_ids if item), "土石方结构化审计缺项"
    if project_comparison_status == "mismatch":
        details = _project_comparison_detail_text(project_comparison)
        actual = "项目概要与立项或主体设计文件存在关键建设规模差异"
        return f"{actual}：{details}" if details else actual, "项目组成一致性不通过" + (f"：{details}" if details else "")
    if project_comparison_status == "needs_review":
        details = _project_comparison_detail_text(project_comparison)
        actual = "项目概要或立项/主体设计文件缺少可结构化比较字段"
        return f"{actual}：{details}" if details else actual, "项目组成一致性证据不足" + (f"：{details}" if details else "")
    return "配置化审查命中待复核条件", "配置化审查需复核"


def _project_comparison_detail_text(project_comparison: dict[str, Any] | None) -> str:
    if not isinstance(project_comparison, dict):
        return ""
    key_findings = project_comparison.get("key_findings")
    if isinstance(key_findings, list):
        details = [str(item).strip() for item in key_findings if str(item).strip()]
        if details:
            return "；".join(details[:3])
    reason = str(project_comparison.get("reason") or "").strip()
    return reason


def _generic_rule_issue_desc(rule: dict[str, Any], matched: list[str], missing: list[str]) -> str:
    rule_name = str(rule.get("rule_name") or "规则库审查")
    matched_text = "、".join(matched) if matched else "无"
    missing_text = "、".join(missing[:6]) if missing else "无"
    requirement = str(rule.get("evidence_requirement") or "应满足规则库证据要求")
    return (
        f"{rule_name}：按目标字段逐项核验，材料中已定位「{matched_text}」，"
        f"但未定位到「{missing_text}」。依据规则要求“{requirement}”，判定为证据不足，需要复核。"
    )


def _generic_rule_reasoning(rule: dict[str, Any], matched: list[str], missing: list[str]) -> dict[str, Any]:
    target_fields = [str(item) for item in rule.get("target_fields", []) if str(item).strip()]
    requirement = str(rule.get("evidence_requirement") or "应满足规则库证据要求")
    rule_source = str(rule.get("rule_source") or "")
    severity_policy = str(rule.get("severity_policy") or "")
    steps = [
        f"1. 读取规则目标字段：{'、'.join(target_fields) or '-'}。",
        f"2. 在当前审查对象全文中检索目标字段，已命中：{'、'.join(matched) if matched else '无'}。",
        f"3. 未命中字段按“材料中未见明确表述”处理，待核验：{'、'.join(missing) if missing else '无'}。",
        f"4. 规则要求：{requirement}",
        "5. 只要存在必需目标字段未形成可核验证据，就不判定通过，输出为证据不足/需复核。",
    ]
    if severity_policy:
        steps.append(f"6. 风险等级口径：{severity_policy}")
    return {
        "matched_target_fields": matched,
        "missing_target_fields": missing,
        "target_fields": target_fields,
        "rule_source": rule_source,
        "severity_policy": severity_policy,
        "evidence_requirement": requirement,
        "judgement_basis": (
            f"{rule_source + '；' if rule_source else ''}"
            f"规则要求：{requirement}；"
            "判定逻辑：target_fields 中的字段必须在方案正文、附表、附图或支撑材料中形成可核验证据；"
            "未命中的目标字段按材料中未见明确表述处理。"
        ),
        "judgement_steps": steps,
    }


def _evidence_matches_from_slot_package(
    evidence_slot_package: dict[str, Any],
    chunks: list[ReviewChunk],
    limit: int = 8,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in evidence_slot_package.get("slots", []):
        if not isinstance(slot, dict):
            continue
        for key in ["prompt_matches", "trace_matches", "matches"]:
            for match in slot.get(key, []):
                if not isinstance(match, dict):
                    continue
                chunk_id = str(match.get("chunk_id") or "")
                if chunk_id and chunk_id in seen:
                    continue
                seen.add(chunk_id)
                enriched = dict(match)
                enriched["slot_id"] = slot.get("slot_id")
                enriched["slot_label"] = slot.get("label")
                if not enriched.get("anchors"):
                    chunk = _chunk_for_evidence_match(chunks, enriched)
                    if chunk:
                        enriched.update(_evidence_match_from_chunk(chunk, []))
                matches.append(enriched)
                if len(matches) >= limit:
                    return matches
    return matches


def _evidence_matches_from_chunks(
    chunks: list[ReviewChunk],
    keywords: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, ReviewChunk, list[str]]] = []
    normalized_keywords = [keyword for keyword in keywords if keyword]
    for index, chunk in enumerate(chunks):
        text = chunk.text or ""
        matched_terms = [keyword for keyword in normalized_keywords if keyword in text]
        if not matched_terms:
            continue
        scored.append((len(matched_terms), -index, chunk, matched_terms))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [_evidence_match_from_chunk(chunk, matched_terms) for _, _, chunk, matched_terms in scored[:limit]]


def _evidence_matches_from_chunk(chunk: ReviewChunk | None) -> list[dict[str, Any]]:
    return [_evidence_match_from_chunk(chunk, [])] if chunk else []


def _evidence_match_from_chunk(chunk: ReviewChunk, matched_terms: list[str]) -> dict[str, Any]:
    page_start = chunk.page_range[0] if chunk.page_range else None
    page_end = chunk.page_range[-1] if chunk.page_range else page_start
    anchors = chunk.bbox_list or []
    block_ids = [str(anchor.get("block_id")) for anchor in anchors if anchor.get("block_id")]
    return {
        "chunk_id": chunk.chunk_id,
        "page": page_start,
        "page_end": page_end,
        "primary_page": page_start,
        "page_range": [page_start, page_end] if page_start is not None and page_end is not None else [],
        "section": chunk.section,
        "anchors": anchors,
        "block_ids": block_ids,
        "bbox_count": len(anchors),
        "matched_terms": matched_terms,
        "retrieval_sources": ["keyword"],
        "text": chunk.text[:1600],
    }


def _chunk_for_evidence_match(chunks: list[ReviewChunk], match: dict[str, Any]) -> ReviewChunk | None:
    chunk_id = str(match.get("chunk_id") or "")
    if not chunk_id:
        return None
    return next((chunk for chunk in chunks if chunk.chunk_id == chunk_id), None)


def _source_bbox_list_from_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in matches:
        for anchor in match.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            key = f"{anchor.get('page')}:{anchor.get('block_id')}:{anchor.get('bbox')}"
            if key in seen:
                continue
            seen.add(key)
            anchors.append(anchor)
    return anchors


def _block_ids_from_matches(matches: list[dict[str, Any]]) -> list[str]:
    block_ids: list[str] = []
    seen: set[str] = set()
    for match in matches:
        candidates = match.get("block_ids")
        if not isinstance(candidates, list):
            candidates = [anchor.get("block_id") for anchor in match.get("anchors", []) if isinstance(anchor, dict)]
        for block_id in candidates:
            text = str(block_id or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            block_ids.append(text)
    return block_ids


def _source_pages_from_matches(matches: list[dict[str, Any]]) -> list[int]:
    pages: set[int] = set()
    for match in matches:
        for key in ["page", "primary_page"]:
            value = match.get(key)
            if isinstance(value, int):
                pages.add(value)
        page_range = match.get("page_range")
        if isinstance(page_range, list):
            pages.update(int(page) for page in page_range if isinstance(page, int))
    return sorted(page for page in pages if page > 0)


def _evidence_text_from_matches(matches: list[dict[str, Any]], limit: int = 5) -> str:
    lines: list[str] = []
    for index, match in enumerate(matches[:limit], start=1):
        page = match.get("page") or match.get("primary_page") or "-"
        chunk_id = str(match.get("chunk_id") or "-")
        section = str(match.get("section") or "").strip()
        text = re.sub(r"\s+", " ", str(match.get("text") or "")).strip()
        if not text:
            continue
        prefix = f"{index}. {chunk_id} p.{page}"
        if section:
            prefix += f" {section}"
        lines.append(f"{prefix}：{text[:320]}")
    return "\n".join(lines)


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


def _structured_issue_keywords(rule: dict[str, Any], evidence_slot_package: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    for slot in evidence_slot_package.get("slots", []):
        if not isinstance(slot, dict):
            continue
        keywords.extend(str(term) for term in slot.get("matched_expected_terms", []) if str(term).strip())
        keywords.extend(str(term) for term in slot.get("expected_terms", []) if str(term).strip())
    keywords.extend(str(item) for item in rule.get("target_fields", []) if str(item).strip())
    return keywords or [str(rule.get("rule_name") or rule.get("review_sub_type") or "")]


def _severity_from_policy(policy: str) -> str:
    if "重大" in policy or "严重" in policy:
        return "HIGH"
    if "一般" in policy:
        return "MEDIUM"
    return "LOW"

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


def _to_number(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
