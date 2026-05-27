"""Review-check-item driven RAG preview agent."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.config import get_llm, settings
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.services.review_executor_service import execute_check_item_precheck
from app.services.review_rule_schema import SCMC_TOPIC_SPECS, execute_rule_precheck
from app.services.rag_service import (
    ChromaChunkStore,
    RAGReviewError,
    SiliconFlowEmbeddingProvider,
    retrieve_for_rules,
)
from app.services.retrieval_match_serializer import serialize_retrieval_location, serialize_retrieval_match
from app.services.water_review_service import ReviewChunk, build_chunks, parse_document


class ReviewAgentBadRequest(ValueError):
    """Raised when the current session cannot support agent preview."""


class ReviewAgentUnavailable(RuntimeError):
    """Raised when required external AI services are not configured."""


def preview_check_item_with_agent(session_id: str, check_item: dict[str, Any], db: Session) -> dict[str, Any]:
    """Run a non-persistent RAG + LLM preview for a draft review check item."""
    _ensure_agent_dependencies()
    session = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        raise ReviewAgentBadRequest("当前 session 不存在")
    contract = db.query(Contract).filter(Contract.id == session.contract_id).first()
    if not contract:
        raise ReviewAgentBadRequest("当前 session 缺少关联方案文件")

    artifact_dir = _artifact_dir_for_contract(contract)
    chunks = _load_or_build_chunks(contract, artifact_dir)
    if not chunks:
        raise ReviewAgentBadRequest("当前 session 缺少可召回文档内容")

    facts = _load_json_list(artifact_dir / "langextract_facts.json")
    findings = _load_json_list(artifact_dir / "cross_chapter_findings.json")
    rule = _check_item_to_agent_rule(check_item)
    try:
        retrieval = _retrieve_for_check_item(session_id, chunks, rule, facts, findings)
    except RAGReviewError as exc:
        raise ReviewAgentUnavailable(f"RAG 召回失败: {exc}") from exc
    evidence = retrieval.get("matches", [])[:8]
    structured_facts = retrieval.get("structured_facts", []) or []
    cross_findings = retrieval.get("cross_chapter_findings", []) or []
    rule_precheck = execute_rule_precheck(rule, evidence, structured_facts, cross_findings)
    evidence_bundle = _build_evidence_bundle(check_item, retrieval, evidence, structured_facts, cross_findings)
    executor_precheck = execute_check_item_precheck(check_item, evidence_bundle)
    precheck_result = {
        **executor_precheck,
        "rule_execution_result": rule_precheck,
    }
    review_conclusion = _call_preview_llm(
        rule,
        evidence,
        structured_facts,
        cross_findings,
        precheck_result,
        evidence_bundle["regulation_context"],
    )
    return {
        "check_item": check_item,
        "evidence_bundle": evidence_bundle,
        "precheck_result": precheck_result,
        "review_conclusion": review_conclusion,
        "suggested_rule_improvements": _suggest_rule_improvements(check_item, evidence_bundle, review_conclusion),
        "agent_trace": {
            "query": retrieval.get("query", ""),
            "retrieval_mode": "vector_bm25_neighbor_rerank",
            "llm_model": settings.review_llm_model or settings.deepseek_model,
            "persisted": False,
            "artifact_dir": str(artifact_dir),
            "chunk_count": len(chunks),
            "facts_available": bool(facts),
            "cross_chapter_findings_available": bool(findings),
            "vector_store": str(Path(settings.storage_path) / "vector_stores" / "water_review" / session_id),
        },
    }


def _ensure_agent_dependencies() -> None:
    if not settings.siliconflow_api_key:
        raise ReviewAgentUnavailable("SILICONFLOW_API_KEY 缺失，无法执行向量召回")
    if not (settings.review_llm_api_key or settings.deepseek_api_key):
        raise ReviewAgentUnavailable("REVIEW_LLM_API_KEY 或 DEEPSEEK_API_KEY 缺失，无法执行 LLM 试审")


def _artifact_dir_for_contract(contract: Contract) -> Path:
    storage_artifact_dir = Path(settings.storage_path) / "contracts" / contract.id / "water_review"
    candidates = [storage_artifact_dir]
    if contract.file_path:
        file_path = Path(contract.file_path)
        candidates.append(file_path.parent / "water_review")
        if not file_path.is_absolute():
            candidates.append(Path.cwd() / file_path.parent / "water_review")
    for candidate in candidates:
        if (candidate / "review_chunks.json").exists():
            return candidate
    return storage_artifact_dir


def _load_or_build_chunks(contract: Contract, artifact_dir: Path) -> list[ReviewChunk]:
    chunks = _load_review_chunks(artifact_dir / "review_chunks.json")
    if chunks:
        return chunks
    try:
        blocks = parse_document(contract.file_path or None)
        rebuilt_chunks = build_chunks(blocks)
    except Exception as exc:
        raise ReviewAgentBadRequest(f"无法重建 review_chunks: {exc}") from exc
    if rebuilt_chunks:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "review_chunks.json").write_text(
            json.dumps([asdict(chunk) for chunk in rebuilt_chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return rebuilt_chunks


def _load_review_chunks(path: Path) -> list[ReviewChunk]:
    items = _load_json_list(path)
    chunks: list[ReviewChunk] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            chunks.append(
                ReviewChunk(
                    chunk_id=str(item.get("chunk_id") or ""),
                    text=str(item.get("text") or ""),
                    section=str(item.get("section") or ""),
                    page_range=[int(page) for page in item.get("page_range", [])] or [1, 1],
                    bbox_list=item.get("bbox_list") if isinstance(item.get("bbox_list"), list) else [],
                    table_refs=item.get("table_refs") if isinstance(item.get("table_refs"), list) else [],
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    char_start=int(item.get("char_start") or 0),
                    char_end=int(item.get("char_end") or 0),
                )
            )
        except Exception:
            continue
    return [chunk for chunk in chunks if chunk.chunk_id and chunk.text.strip()]


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _check_item_to_agent_rule(check_item: dict[str, Any]) -> dict[str, Any]:
    topic = _topic_for_id(str(check_item.get("topic_id") or ""))
    source_snapshot = check_item.get("source_rule_snapshot")
    if not isinstance(source_snapshot, dict):
        source_snapshot = {}
    expert_brief = _expert_brief_from_snapshot(source_snapshot)
    expert_query_text = _expert_brief_query_text(expert_brief)
    rule_name = str(
        source_snapshot.get("rule_name")
        or check_item.get("review_sub_type")
        or "未命名审查项"
    )
    review_logic = _review_logic_from_snapshot(source_snapshot) or [
        {
            "type": str(check_item.get("executor_type_id") or "manual_basic"),
            "label": str(check_item.get("review_type") or "人工基础核验"),
        }
    ]
    criteria = _join_texts(
        str(check_item.get("review_criteria") or ""),
        expert_brief.get("review_objective", ""),
        expert_brief.get("evidence_instruction", ""),
        expert_brief.get("judgement_basis", ""),
    )
    expected = _join_texts(
        str(check_item.get("expected_result") or check_item.get("conclusion") or ""),
        expert_brief.get("pass_condition", ""),
    )
    failure_conditions = [str(item) for item in check_item.get("failure_conditions", []) if str(item).strip()]
    issue_condition = expert_brief.get("issue_condition", "")
    if issue_condition and issue_condition not in failure_conditions:
        failure_conditions.append(issue_condition)
    regulation_clauses = [str(item) for item in check_item.get("regulation_clauses", []) if str(item).strip()]
    regulation_text = expert_brief.get("regulation_text", "")
    if regulation_text and regulation_text not in regulation_clauses:
        regulation_clauses.append(regulation_text)
    evidence_requirement = _join_texts(
        expert_brief.get("evidence_instruction", ""),
        expected,
        str(source_snapshot.get("evidence_requirement") or ""),
    )
    rule_source = _join_texts("；".join(regulation_clauses), str(source_snapshot.get("rule_source") or ""))
    return {
        "rule_id": str(check_item.get("rule_id") or source_snapshot.get("rule_id") or "draft-preview"),
        "rule_name": rule_name,
        "category": topic.get("name", "SCMC"),
        "review_topic": {"id": topic["id"], "name": topic["name"], "category": "SCMC"},
        "review_item": {"name": str(check_item.get("review_sub_type") or rule_name)},
        "review_logic": review_logic,
        "evidence_scope": check_item.get("evidence_scope") if isinstance(check_item.get("evidence_scope"), dict) else {},
        "target_fields": [str(item) for item in check_item.get("target_fields", []) if str(item).strip()],
        "rule_source": rule_source,
        "regulation_clauses": regulation_clauses,
        "review_criteria": criteria,
        "expected_result": expected,
        "failure_conditions": failure_conditions,
        "evidence_requirement": evidence_requirement,
        "severity_policy": "；".join(failure_conditions) or criteria,
        "expert_brief": expert_brief,
        "expert_brief_query": expert_query_text,
        "rule_execution": {
            "mode": "draft_check_item_agent_preview",
            "checks": [
                {"type": "rag_retrieval", "description": "按审查项召回原文 chunk、结构化事实和跨章节线索。"},
                {"type": "llm_adjudication", "description": "基于召回证据输出单条试审结论。"},
            ],
        },
    }


def _expert_brief_from_snapshot(source_snapshot: dict[str, Any]) -> dict[str, str]:
    brief = source_snapshot.get("expert_brief")
    if not isinstance(brief, dict):
        return {}
    keys = (
        "item_name",
        "review_objective",
        "evidence_instruction",
        "judgement_basis",
        "pass_condition",
        "issue_condition",
        "regulation_text",
    )
    return {key: str(brief.get(key) or "").strip() for key in keys if str(brief.get(key) or "").strip()}


def _expert_brief_query_text(expert_brief: dict[str, str]) -> str:
    return _join_texts(
        expert_brief.get("item_name", ""),
        expert_brief.get("review_objective", ""),
        expert_brief.get("evidence_instruction", ""),
        expert_brief.get("judgement_basis", ""),
        expert_brief.get("pass_condition", ""),
        expert_brief.get("issue_condition", ""),
        expert_brief.get("regulation_text", ""),
    )


def _join_texts(*values: str) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return "\n".join(result)


def _topic_for_id(topic_id: str) -> dict[str, Any]:
    return next((spec for spec in SCMC_TOPIC_SPECS if spec["id"] == topic_id), SCMC_TOPIC_SPECS[0])


def _review_logic_from_snapshot(source_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("review_logic",):
        value = source_snapshot.get(key)
        if isinstance(value, list):
            result = [
                {"type": str(item.get("type") or ""), "label": str(item.get("label") or "")}
                for item in value
                if isinstance(item, dict) and (item.get("type") or item.get("label"))
            ]
            if result:
                return result
    reasoning = source_snapshot.get("reasoning_process")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("review_logic"), list):
        return _review_logic_from_snapshot({"review_logic": reasoning["review_logic"]})
    return []


def _retrieve_for_check_item(
    session_id: str,
    chunks: list[ReviewChunk],
    rule: dict[str, Any],
    facts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    vector_dir = Path(settings.storage_path) / "vector_stores" / "water_review" / session_id
    vector_dir.mkdir(parents=True, exist_ok=True)
    store = ChromaChunkStore(vector_dir, session_id, SiliconFlowEmbeddingProvider())
    store.rebuild(chunks)
    retrievals = retrieve_for_rules(store, chunks, [rule], top_k=settings.rag_top_k, facts=facts, findings=findings)
    return retrievals[0] if retrievals else {"matches": [], "query": ""}


def _build_evidence_bundle(
    check_item: dict[str, Any],
    retrieval: dict[str, Any],
    evidence: list[dict[str, Any]],
    structured_facts: list[dict[str, Any]],
    cross_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    target_fields = [str(item) for item in check_item.get("target_fields", []) if str(item).strip()]
    evidence_text = "\n".join(str(match.get("document", "")) for match in evidence)
    fact_text = "\n".join(
        " ".join(
            str(fact.get(key) or "")
            for key in ("field_name", "field_label", "value", "normalized_value", "source_text")
        )
        for fact in structured_facts
    )
    haystack = f"{evidence_text}\n{fact_text}"
    matched_fields = [field for field in target_fields if field and field in haystack]
    missing_fields = [field for field in target_fields if field and field not in matched_fields]
    retrieval_matches = [serialize_retrieval_match(match) for match in evidence]
    return {
        "evidence_texts": [item["text"] for item in retrieval_matches],
        "evidence_locations": [serialize_retrieval_location(match) for match in evidence],
        "retrieval_matches": retrieval_matches,
        "matched_target_fields": matched_fields,
        "missing_target_fields": missing_fields,
        "structured_facts": structured_facts,
        "cross_reference_findings": cross_findings,
        "langextract_grounding": {
            "fact_count": len(structured_facts),
            "finding_count": len(cross_findings),
            "source": "langextract",
        },
        "regulation_context": _regulation_context(check_item),
        "retrieval_score": retrieval.get("candidate_score", 0),
        "source": "rag_agent",
    }

def _regulation_context(check_item: dict[str, Any]) -> list[dict[str, Any]]:
    clauses = [str(item) for item in check_item.get("regulation_clauses", []) if str(item).strip()]
    snapshot = check_item.get("source_rule_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    context = [{"source": "check_item.regulation_clauses", "text": clause} for clause in clauses]
    expert_brief = _expert_brief_from_snapshot(snapshot)
    if expert_brief.get("regulation_text"):
        context.append(
            {
                "source": "source_rule_snapshot.expert_brief.regulation_text",
                "text": expert_brief["regulation_text"],
            }
        )
    for key in ("rule_source", "evidence_requirement", "review_criteria", "expected_result"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            context.append({"source": f"source_rule_snapshot.{key}", "text": value.strip()})
    return context


def _call_preview_llm(
    rule: dict[str, Any],
    evidence: list[dict[str, Any]],
    structured_facts: list[dict[str, Any]],
    cross_findings: list[dict[str, Any]],
    precheck_result: dict[str, Any],
    regulation_context: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = {
        "review_check_item": {
            "topic": rule.get("review_topic", {}),
            "item": rule.get("review_item", {}),
            "rule_id": rule.get("rule_id"),
            "rule_name": rule.get("rule_name"),
            "review_logic": rule.get("review_logic", []),
            "evidence_scope": rule.get("evidence_scope", {}),
            "target_fields": rule.get("target_fields", []),
            "review_criteria": rule.get("review_criteria"),
            "expected_result": rule.get("expected_result"),
            "failure_conditions": rule.get("failure_conditions", []),
        },
        "regulation_context": regulation_context,
        "precheck_result": precheck_result,
        "evidence": [
            {
                "chunk_id": match.get("chunk_id"),
                "page_start": match.get("metadata", {}).get("page_start"),
                "page_end": match.get("metadata", {}).get("page_end"),
                "section": match.get("metadata", {}).get("section"),
                "text": str(match.get("document", ""))[:1200],
            }
            for match in evidence[:8]
        ],
        "structured_facts": structured_facts[:12],
        "cross_reference_findings": cross_findings[:6],
        "output_schema": {
            "status": "pass|issue|needs_review|potential_issue",
            "summary": "单条审查结论摘要",
            "actual_value": "证据中的实际情况",
            "expected_value": "规则要求或预期结果",
            "fix_suggestion": "需要补充或修改的内容",
            "confidence": "0-100整数",
            "next_action": "下一步建议",
        },
    }
    messages = [
        SystemMessage(
            content=(
                "你是水土保持方案审查专家。只基于提供的审查项、法规上下文、"
                "召回证据、LangExtract事实和预检查结果输出 JSON。不得新增证据外事实，"
                "不得输出 markdown。"
            )
        ),
        HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
    ]
    try:
        response = get_llm().invoke(messages)
        content = str(response.content).strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()
        data = json.loads(content)
    except Exception as exc:
        raise ReviewAgentUnavailable(f"LLM 试审失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewAgentUnavailable("LLM 试审结果不是 JSON 对象")
    return {
        "status": str(data.get("status") or "needs_review"),
        "summary": str(data.get("summary") or ""),
        "actual_value": str(data.get("actual_value") or ""),
        "expected_value": str(data.get("expected_value") or rule.get("expected_result") or ""),
        "fix_suggestion": str(data.get("fix_suggestion") or ""),
        "confidence": int(data.get("confidence") or 0),
        "next_action": str(data.get("next_action") or ""),
        "llm_required": False,
    }


def _suggest_rule_improvements(
    check_item: dict[str, Any],
    evidence_bundle: dict[str, Any],
    review_conclusion: dict[str, Any],
) -> list[str]:
    suggestions: list[str] = []
    if evidence_bundle.get("missing_target_fields"):
        suggestions.append("复核 target_fields：存在未命中的目标字段，可能需要调整字段名或扩大证据范围。")
    if not evidence_bundle.get("retrieval_matches"):
        suggestions.append("当前审查项未召回原文 chunk，建议补充章节、表格或关键字段。")
    if not evidence_bundle.get("regulation_context"):
        suggestions.append("建议补充 regulation_clauses，方便 LLM 将证据与法规条款对齐。")
    if review_conclusion.get("status") in {"needs_review", "potential_issue"}:
        suggestions.append("建议专家检查 expected_result 与 failure_conditions 是否足够具体。")
    if not any(check_item.get("evidence_scope", {}).values()):
        suggestions.append("建议填写 evidence_scope，明确章节、表格、附件或法规召回范围。")
    return suggestions or ["当前审查项已完成真实召回试审，可保存前由专家确认结论口径。"]
