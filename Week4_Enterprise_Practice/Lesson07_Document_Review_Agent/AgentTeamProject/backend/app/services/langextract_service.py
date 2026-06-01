"""LangExtract-grounded evidence extraction for water review.

This layer sits after bbox-aware chunking and before RAG adjudication.  It uses
LangExtract for source-grounded extraction, then maps character intervals back
to the chunk/page/bbox metadata produced by MinerU or parser fallbacks.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class LangExtractReviewError(RuntimeError):
    """Raised when the LangExtract grounding path cannot complete safely."""


@dataclass
class EvidenceFact:
    fact_id: str
    field_name: str
    value: str
    normalized_value: str
    unit: str
    section: str
    chunk_id: str
    page_range: list[int]
    source_text: str
    char_interval: dict[str, int | None]
    block_ids: list[str]
    bbox_list: list[dict[str, Any]]
    confidence: int
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossChapterFinding:
    finding_id: str
    finding_type: str
    field_name: str
    description: str
    risk_level: str
    actual_value: str
    expected_value: str
    fact_ids: list[str]
    source_pages: list[int]
    bbox_list: list[dict[str, Any]]
    evidence_text: str
    confidence: int
    attributes: dict[str, Any] = field(default_factory=dict)


FIELD_ORDER = [
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "key_prevention_or_control_area",
    "disturbed_area",
    "land_area",
    "prevention_responsibility_area",
    "zone_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "comprehensive_utilization",
    "spoil_destination",
    "topsoil_stripping",
    "topsoil_preservation",
    "topsoil_backfill",
    "temp_soil_stockpile",
    "borrow_area",
    "spoil_area",
    "construction_road",
    "prevention_measures",
    "monitoring",
    "schedule_arrangement",
    "investment_estimate",
]


LANGEXTRACT_ALLOWED_FIELDS = (
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "land_area",
    "disturbed_area",
    "prevention_responsibility_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "spoil_destination",
    "borrow_area",
    "comprehensive_utilization",
)


FIELD_LABELS = {
    "project_name": "项目名称",
    "construction_unit": "建设单位",
    "construction_location": "建设地点",
    "project_nature": "建设性质",
    "key_prevention_or_control_area": "重点防治区属性",
    "disturbed_area": "扰动地表面积",
    "land_area": "占地面积",
    "prevention_responsibility_area": "防治责任范围面积",
    "zone_area": "分区面积",
    "excavation_volume": "挖方",
    "fill_volume": "填方",
    "borrow_volume": "借方",
    "spoil_volume": "弃方",
    "comprehensive_utilization": "综合利用",
    "spoil_destination": "外运去向",
    "topsoil_stripping": "表土剥离",
    "topsoil_preservation": "表土保存",
    "topsoil_backfill": "表土回覆",
    "temp_soil_stockpile": "临时堆土区",
    "borrow_area": "取土场",
    "spoil_area": "弃渣场",
    "construction_road": "施工道路",
    "prevention_measures": "防治措施",
    "monitoring": "监测",
    "schedule_arrangement": "时序安排",
    "investment_estimate": "投资估算",
}


LANGEXTRACT_PROMPT_FIELD_LABELS = {
    field_name: FIELD_LABELS[field_name]
    for field_name in LANGEXTRACT_ALLOWED_FIELDS
}


FIELD_ALIASES = {
    "occupied_area": "land_area",
    "responsibility_area": "prevention_responsibility_area",
    "water_soil_conservation_investment": "investment_estimate",
    "spoil_ground": "spoil_area",
    "borrow_ground": "borrow_area",
}


FACT_KEYWORDS = [
    "项目名称",
    "建设单位",
    "建设地点",
    "建设性质",
    "重点预防区",
    "重点治理区",
    "水土流失",
    "扰动",
    "占地",
    "防治责任范围",
    "面积",
    "土石方",
    "挖方",
    "填方",
    "借方",
    "弃方",
    "余方",
    "综合利用",
    "外运",
    "弃渣",
    "弃土",
    "表土",
    "剥离",
    "保存",
    "回覆",
    "回填",
    "取土场",
    "弃渣场",
    "临时堆土",
    "施工道路",
    "施工便道",
    "工程措施",
    "植物措施",
    "临时措施",
    "监测",
    "投资",
    "时序",
]


HIGH_VALUE_SECTIONS = [
    "综合说明",
    "项目概况",
    "工程概况",
    "防治责任范围",
    "土石方",
    "表土",
    "弃渣",
    "取土",
    "临时堆土",
    "防治措施",
    "监测",
    "投资估算",
]


PROMPT_DESCRIPTION = """
你是水土保持方案技术审查的证据抽取器。请只抽取原文中明确出现的事实，
并尽量使用原文中的最小连续文本作为 extraction_text，不要改写、不要推测。

允许的 extraction_class 只使用以下英文名：
project_name, construction_unit, construction_location, project_nature,
land_area, disturbed_area, prevention_responsibility_area,
excavation_volume, fill_volume, borrow_volume, spoil_volume,
spoil_destination, borrow_area, comprehensive_utilization。

attributes 中尽量给出：
- normalized_value：归一化后的数值或短语
- unit：单位，如 hm²、万m³、万元
- scope：事实所属范围，如项目区、主体工程区、临时堆土区
- evidence_role：main/table/context
- confidence：0-100
""".strip()


def run_langextract(chunks: list[Any]) -> list[dict[str, Any]]:
    """Run real LangExtract over candidate chunks and return fact dicts."""
    if not settings.langextract_enabled:
        return []
    if not chunks:
        return []

    api_key = settings.review_llm_api_key or settings.deepseek_api_key
    base_url = settings.review_llm_base_url or settings.deepseek_base_url
    model_id = settings.review_llm_model or settings.deepseek_model
    if not api_key:
        raise LangExtractReviewError("REVIEW_LLM_API_KEY or DEEPSEEK_API_KEY is required for LangExtract")

    try:
        import langextract as lx
        from langextract import prompt_validation as prompt_validation
    except Exception as exc:
        raise LangExtractReviewError("langextract package is not available") from exc

    selected_chunks = _select_candidate_chunks(chunks)
    documents = [
        lx.data.Document(
            text=_chunk_text(chunk),
            document_id=_chunk_id(chunk),
            additional_context=f"section={getattr(chunk, 'section', '')}; pages={getattr(chunk, 'page_range', [])}",
        )
        for chunk in selected_chunks
        if _chunk_text(chunk).strip()
    ]
    if not documents:
        return []

    chunk_by_id = {_chunk_id(chunk): chunk for chunk in selected_chunks}
    model = _create_timeout_openai_model(model_id, api_key, base_url)

    annotated_docs: list[Any] = []
    failed_documents: list[dict[str, str]] = []
    started_at = time.monotonic()
    deadline = started_at + max(settings.langextract_stage_timeout_seconds, 1)
    for document in documents:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failed_documents.append({"document_id": _document_id(document), "error": "LangExtract stage timeout"})
            logger.warning(
                "langextract_stage_timeout selected_document_count=%s failed_document_count=%s timeout_seconds=%s",
                len(documents),
                len(failed_documents),
                settings.langextract_stage_timeout_seconds,
            )
            break
        try:
            result = _extract_one_document_with_timeout(
                lx,
                prompt_validation,
                model,
                document,
                timeout_seconds=min(max(settings.langextract_request_timeout, 1), remaining),
            )
            annotated_docs.extend(result if isinstance(result, list) else [result])
        except TimeoutError as exc:
            failed_documents.append({"document_id": _document_id(document), "error": str(exc)[:500]})
            logger.warning("langextract_document_timeout document_id=%s error=%s", _document_id(document), exc)
            break
        except Exception as exc:
            failed_documents.append({"document_id": _document_id(document), "error": str(exc)[:500]})
            logger.warning("langextract_document_failed document_id=%s error=%s", _document_id(document), exc)

    if failed_documents and len(failed_documents) == len(documents):
        raise LangExtractReviewError(f"LangExtract extraction failed for all documents: {failed_documents[:3]}")

    facts: list[EvidenceFact] = []
    for annotated in annotated_docs:
        document_id = _document_id(annotated)
        chunk = chunk_by_id.get(document_id)
        if not chunk:
            continue
        for extraction in getattr(annotated, "extractions", []) or []:
            fact = _fact_from_extraction(extraction, chunk, len(facts))
            if fact:
                facts.append(fact)
    deduped = _dedupe_facts(facts)
    if not deduped:
        logger.error(
            "langextract_no_grounded_facts selected_chunk_count=%s document_count=%s annotated_doc_count=%s "
            "raw_fact_count=%s failed_document_count=%s",
            len(selected_chunks),
            len(documents),
            len(annotated_docs),
            len(facts),
            len(failed_documents),
        )
        raise LangExtractReviewError("LangExtract completed but produced no grounded facts")
    return [asdict(fact) for fact in deduped]


def _extract_one_document_with_timeout(
    lx: Any,
    prompt_validation: Any,
    model: Any,
    document: Any,
    *,
    timeout_seconds: float,
) -> list[Any]:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(("ok", _extract_one_document(lx, prompt_validation, model, document)))
        except BaseException as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=max(timeout_seconds, 1))
    if thread.is_alive():
        raise TimeoutError(f"LangExtract document timed out after {int(timeout_seconds)} seconds")
    status, payload = result_queue.get_nowait()
    if status == "error":
        raise payload
    return payload


def _extract_one_document(lx: Any, prompt_validation: Any, model: Any, document: Any) -> list[Any]:
    result = lx.extract(
        text_or_documents=[document],
        prompt_description=PROMPT_DESCRIPTION,
        examples=_examples(lx),
        model=model,
        use_schema_constraints=False,
        max_char_buffer=settings.langextract_max_char_buffer,
        extraction_passes=settings.langextract_extraction_passes,
        batch_length=1,
        max_workers=1,
        temperature=0.0,
        fetch_urls=False,
        show_progress=False,
        prompt_validation_level=prompt_validation.PromptValidationLevel.OFF,
        resolver_params={"suppress_parse_errors": True},
        language_model_params={"max_output_tokens": 4096},
    )
    return result if isinstance(result, list) else [result]


def _create_timeout_openai_model(model_id: str, api_key: str, base_url: str) -> Any:
    """Create a LangExtract OpenAI-compatible model with a bounded request timeout."""
    try:
        import openai
        from langextract.providers.openai import OpenAILanguageModel
    except Exception as exc:
        raise LangExtractReviewError("langextract OpenAI provider is not available") from exc

    model = OpenAILanguageModel(
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_workers=max(settings.langextract_max_workers, 1),
    )
    model._client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=settings.langextract_request_timeout,
    )
    return model


def facts_to_extracted_fields(
    facts: list[dict[str, Any]],
    fallback_fields: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert grounded facts into the existing ExtractedField payload shape."""
    by_name: dict[str, dict[str, Any]] = {
        field.get("field_name", ""): dict(field)
        for field in (fallback_fields or [])
        if field.get("field_name")
    }

    for fact in sorted(facts, key=lambda item: int(item.get("confidence") or 0), reverse=True):
        field_name = _normalize_field_name(str(fact.get("field_name", "")))
        if field_name not in FIELD_ORDER:
            continue
        if field_name in by_name and by_name[field_name].get("fact_id"):
            continue
        interval = fact.get("char_interval") or {}
        page_range = fact.get("page_range") or [1, 1]
        by_name[field_name] = {
            "field_name": field_name,
            "value": fact.get("value", ""),
            "normalized_value": fact.get("normalized_value") or fact.get("value", ""),
            "source_span": {
                "char_start": interval.get("start_pos") or 0,
                "char_end": interval.get("end_pos") or 0,
            },
            "section": fact.get("section", ""),
            "unit": fact.get("unit", ""),
            "confidence": fact.get("confidence", 80),
            "source_evidence_text": fact.get("source_text", ""),
            "source_page_number": page_range[0] if page_range else 1,
            "fact_id": fact.get("fact_id"),
        }

    return [by_name.get(name) or _empty_field(name) for name in FIELD_ORDER]


def build_fact_index(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, list[str]] = {}
    for fact in facts:
        by_field.setdefault(str(fact.get("field_name", "")), []).append(str(fact.get("fact_id", "")))
    return {
        "fact_count": len(facts),
        "fields": sorted(by_field),
        "by_field": by_field,
    }


def build_cross_chapter_findings(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[CrossChapterFinding] = []
    facts_by_field = _facts_by_field(facts)

    for field_name in ["disturbed_area", "land_area", "prevention_responsibility_area", "investment_estimate"]:
        findings.extend(_same_field_conflicts(field_name, facts_by_field.get(field_name, [])))

    area_facts = [
        *facts_by_field.get("disturbed_area", []),
        *facts_by_field.get("prevention_responsibility_area", []),
        *facts_by_field.get("land_area", []),
    ]
    findings.extend(_cross_area_conflicts(area_facts))
    earthwork = _earthwork_balance_finding(facts_by_field)
    if earthwork:
        findings.append(earthwork)
    spoil = _spoil_destination_finding(facts_by_field)
    if spoil:
        findings.append(spoil)
    topsoil = _topsoil_chain_finding(facts_by_field)
    if topsoil:
        findings.append(topsoil)

    return [asdict(finding) for finding in _dedupe_findings(findings)]


def _examples(lx: Any) -> list[Any]:
    return [
        lx.data.ExampleData(
            text=(
                "项目名称：某学校图书馆项目。建设单位：某大学。建设地点位于北京市昌平区。"
                "本项目总占地面积1.20hm²，防治责任范围面积1.20hm²。"
            ),
            extractions=[
                lx.data.Extraction("project_name", "某学校图书馆项目"),
                lx.data.Extraction("construction_unit", "某大学"),
                lx.data.Extraction("construction_location", "北京市昌平区"),
                lx.data.Extraction("land_area", "1.20hm²", attributes={"normalized_value": "1.20", "unit": "hm²", "confidence": "92"}),
                lx.data.Extraction("prevention_responsibility_area", "1.20hm²", attributes={"normalized_value": "1.20", "unit": "hm²", "confidence": "92"}),
            ],
        ),
        lx.data.ExampleData(
            text=(
                "土石方总量为18.40万m³，其中挖方9.20万m³，填方8.10万m³，"
                "借方0.00万m³，弃方1.10万m³，余方运往指定消纳场综合利用。"
            ),
            extractions=[
                lx.data.Extraction("excavation_volume", "9.20万m³", attributes={"normalized_value": "9.20", "unit": "万m³", "confidence": "90"}),
                lx.data.Extraction("fill_volume", "8.10万m³", attributes={"normalized_value": "8.10", "unit": "万m³", "confidence": "90"}),
                lx.data.Extraction("borrow_volume", "0.00万m³", attributes={"normalized_value": "0.00", "unit": "万m³", "confidence": "90"}),
                lx.data.Extraction("spoil_volume", "1.10万m³", attributes={"normalized_value": "1.10", "unit": "万m³", "confidence": "90"}),
                lx.data.Extraction("spoil_destination", "运往指定消纳场综合利用", attributes={"confidence": "88"}),
            ],
        ),
    ]


def _select_candidate_chunks(chunks: list[Any]) -> list[Any]:
    ranked: list[tuple[int, int, Any]] = []
    for index, chunk in enumerate(chunks):
        haystack = f"{getattr(chunk, 'section', '')}\n{_chunk_text(chunk)}"
        score = _langextract_candidate_score(haystack)
        if score:
            ranked.append((score, index, chunk))

    if not ranked:
        ranked = [(1, index, chunk) for index, chunk in enumerate(chunks)]

    max_chunks = max(1, settings.langextract_max_chunks)
    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    selected = ranked[:max_chunks]
    selected.sort(key=lambda item: item[1])
    return [chunk for _, _, chunk in selected]


def _langextract_candidate_score(text: str) -> int:
    score = 0
    score += sum(1 for section in HIGH_VALUE_SECTIONS if section in text) * 8
    score += sum(1 for keyword in FACT_KEYWORDS if keyword in text) * 2
    if re.search(r"\d+(?:\.\d+)?\s*(?:hm²|hm2|公顷|亩|万m³|万m3|万立方米|万元)", text, re.I):
        score += 6
    if any(label in text for label in FIELD_LABELS.values()):
        score += 4
    return score


def _fact_from_extraction(extraction: Any, chunk: Any, index: int) -> EvidenceFact | None:
    value = str(getattr(extraction, "extraction_text", "") or "").strip()
    if not value:
        return None
    field_name = _normalize_field_name(str(getattr(extraction, "extraction_class", "") or ""))
    if field_name not in LANGEXTRACT_ALLOWED_FIELDS:
        return None

    attrs = dict(getattr(extraction, "attributes", None) or {})
    interval = getattr(extraction, "char_interval", None)
    local_start = getattr(interval, "start_pos", None) if interval else None
    local_end = getattr(interval, "end_pos", None) if interval else None
    global_start = (getattr(chunk, "char_start", 0) + local_start) if local_start is not None else None
    global_end = (getattr(chunk, "char_start", 0) + local_end) if local_end is not None else None
    normalized_value, unit = _normalize_value(field_name, value, attrs)
    bbox_list = list(getattr(chunk, "bbox_list", []) or [])
    block_ids = [
        str(item.get("block_id"))
        for item in bbox_list
        if isinstance(item, dict) and item.get("block_id")
    ]
    confidence = _confidence(attrs, has_interval=local_start is not None, has_bbox=bool(bbox_list))
    source_text = _source_text(_chunk_text(chunk), value, local_start, local_end)
    digest = hashlib.sha1(f"{field_name}|{value}|{_chunk_id(chunk)}|{index}".encode()).hexdigest()[:10]
    return EvidenceFact(
        fact_id=f"fact-{digest}",
        field_name=field_name,
        value=value,
        normalized_value=normalized_value,
        unit=unit,
        section=getattr(chunk, "section", ""),
        chunk_id=_chunk_id(chunk),
        page_range=list(getattr(chunk, "page_range", []) or [1, 1]),
        source_text=source_text,
        char_interval={"start_pos": global_start, "end_pos": global_end},
        block_ids=block_ids,
        bbox_list=bbox_list,
        confidence=confidence,
        attributes=attrs,
    )


def _same_field_conflicts(field_name: str, facts: list[dict[str, Any]]) -> list[CrossChapterFinding]:
    numeric = [fact for fact in facts if _numeric(fact) is not None]
    findings: list[CrossChapterFinding] = []
    if len(numeric) < 2:
        return findings
    values = sorted(numeric, key=lambda fact: _numeric(fact) or 0)
    low = values[0]
    high = values[-1]
    low_value = _numeric(low) or 0
    high_value = _numeric(high) or 0
    if not _differs(low_value, high_value, 0.03):
        return findings
    findings.append(
        _finding(
            "same_field_conflict",
            field_name,
            f"{FIELD_LABELS.get(field_name, field_name)}在不同章节或表格中出现不一致数值。",
            "MEDIUM",
            f"{low.get('value')} / {high.get('value')}",
            "同一字段跨章节表述应一致，或说明统计口径差异。",
            [low, high],
            confidence=78,
        )
    )
    return findings


def _cross_area_conflicts(facts: list[dict[str, Any]]) -> list[CrossChapterFinding]:
    numeric = [fact for fact in facts if _numeric(fact) is not None]
    if len(numeric) < 2:
        return []
    values = sorted(numeric, key=lambda fact: _numeric(fact) or 0)
    low = values[0]
    high = values[-1]
    if not _differs(_numeric(low) or 0, _numeric(high) or 0, 0.05):
        return []
    return [
        _finding(
            "area_cross_chapter_conflict",
            "area",
            "项目面积、防治责任范围或扰动面积在跨章节证据中存在差异。",
            "MEDIUM",
            f"{FIELD_LABELS.get(low.get('field_name', ''), low.get('field_name', ''))}={low.get('value')}；"
            f"{FIELD_LABELS.get(high.get('field_name', ''), high.get('field_name', ''))}={high.get('value')}",
            "项目概况、防治责任范围和措施设计采用的关键面积应统一，差异需说明口径。",
            [low, high],
            confidence=76,
        )
    ]


def _earthwork_balance_finding(facts_by_field: dict[str, list[dict[str, Any]]]) -> CrossChapterFinding | None:
    excavation = _best_numeric_fact(facts_by_field.get("excavation_volume", []))
    fill = _best_numeric_fact(facts_by_field.get("fill_volume", []))
    borrow = _best_numeric_fact(facts_by_field.get("borrow_volume", []))
    spoil = _best_numeric_fact(facts_by_field.get("spoil_volume", []))
    available = [fact for fact in [excavation, fill, borrow, spoil] if fact]
    if len(available) < 4:
        if available:
            return _finding(
                "earthwork_fields_incomplete",
                "earthwork_balance",
                "土石方平衡核验所需的挖方、填方、借方、弃方字段不完整。",
                "MEDIUM",
                "已抽取：" + "、".join(FIELD_LABELS.get(f["field_name"], f["field_name"]) for f in available),
                "应同时明确挖方、填方、借方、弃方及其统计口径。",
                available,
                confidence=72,
            )
        return None
    left = (_numeric(excavation) or 0) + (_numeric(borrow) or 0)
    right = (_numeric(fill) or 0) + (_numeric(spoil) or 0)
    if not _differs(left, right, 0.05):
        return None
    return _finding(
        "earthwork_balance_conflict",
        "earthwork_balance",
        "土石方平衡关系存在不一致。",
        "HIGH",
        f"挖方+借方={left:g}万m³；填方+弃方={right:g}万m³",
        "挖方+借方应与填方+弃方基本平衡，或说明综合利用、外运和统计口径。",
        [excavation, fill, borrow, spoil],
        confidence=84,
    )


def _spoil_destination_finding(facts_by_field: dict[str, list[dict[str, Any]]]) -> CrossChapterFinding | None:
    spoil = _best_numeric_fact(facts_by_field.get("spoil_volume", []))
    if not spoil or (_numeric(spoil) or 0) <= 0:
        return None
    destinations = [
        *facts_by_field.get("spoil_destination", []),
        *facts_by_field.get("spoil_area", []),
        *facts_by_field.get("comprehensive_utilization", []),
    ]
    if destinations:
        return None
    return _finding(
        "spoil_destination_missing",
        "spoil_destination",
        "材料中存在弃方或余方量，但未抽取到弃土去向、弃渣场或综合利用说明。",
        "HIGH",
        f"弃方={spoil.get('value')}",
        "存在弃方时应明确弃渣场、消纳场或合法综合利用去向。",
        [spoil],
        confidence=80,
    )


def _topsoil_chain_finding(facts_by_field: dict[str, list[dict[str, Any]]]) -> CrossChapterFinding | None:
    has_area = bool(
        facts_by_field.get("disturbed_area")
        or facts_by_field.get("land_area")
        or facts_by_field.get("prevention_responsibility_area")
    )
    if not has_area:
        return None
    topsoil_facts = [
        *facts_by_field.get("topsoil_stripping", []),
        *facts_by_field.get("topsoil_preservation", []),
        *facts_by_field.get("topsoil_backfill", []),
        *facts_by_field.get("temp_soil_stockpile", []),
    ]
    if topsoil_facts:
        return None
    area_fact = _best_numeric_fact(
        facts_by_field.get("disturbed_area", [])
        or facts_by_field.get("land_area", [])
        or facts_by_field.get("prevention_responsibility_area", [])
    )
    related = [area_fact] if area_fact else []
    return _finding(
        "topsoil_chain_missing",
        "topsoil_protection",
        "材料中存在扰动或占地信息，但未抽取到表土剥离、保存、回覆或临时堆存证据。",
        "MEDIUM",
        f"已见面积信息：{area_fact.get('value') if area_fact else '已见占地/扰动表述'}",
        "涉及扰动地表时应说明表土剥离、保存、防护和回覆利用措施。",
        related,
        confidence=74,
    )


def _finding(
    finding_type: str,
    field_name: str,
    description: str,
    risk_level: str,
    actual_value: str,
    expected_value: str,
    facts: list[dict[str, Any]],
    confidence: int,
) -> CrossChapterFinding:
    fact_ids = [str(fact.get("fact_id", "")) for fact in facts if fact]
    digest = hashlib.sha1("|".join([finding_type, field_name, *fact_ids]).encode()).hexdigest()[:10]
    pages = sorted({
        int(page)
        for fact in facts
        for page in (fact.get("page_range") or [])
        if str(page).isdigit()
    })
    bbox_list = [bbox for fact in facts for bbox in (fact.get("bbox_list") or [])]
    evidence_text = "\n".join(str(fact.get("source_text", "")) for fact in facts if fact.get("source_text"))
    return CrossChapterFinding(
        finding_id=f"finding-{digest}",
        finding_type=finding_type,
        field_name=field_name,
        description=description,
        risk_level=risk_level,
        actual_value=actual_value,
        expected_value=expected_value,
        fact_ids=fact_ids,
        source_pages=pages,
        bbox_list=bbox_list,
        evidence_text=evidence_text[:1200],
        confidence=confidence,
        attributes={"source": "langextract"},
    )


def _normalize_field_name(name: str) -> str:
    clean = name.strip()
    return FIELD_ALIASES.get(clean, clean)


def _normalize_value(field_name: str, value: str, attrs: dict[str, Any]) -> tuple[str, str]:
    attr_value = str(attrs.get("normalized_value") or "").strip()
    attr_unit = str(attrs.get("unit") or "").strip()
    parsed_value, parsed_unit = _parse_numeric_with_unit(value)
    unit = attr_unit or parsed_unit
    if parsed_value is None:
        return attr_value or value, unit
    normalized, normalized_unit = _normalize_metric(field_name, parsed_value, unit)
    return f"{normalized:g}", normalized_unit or unit


def _parse_numeric_with_unit(value: str) -> tuple[float | None, str]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([万亿]?(?:m3|m³|立方米|万立方米|hm2|hm²|公顷|亩|m2|m²|平方米|万元|亿元|元)?)", value, re.I)
    if not match:
        return None, ""
    return float(match.group(1)), match.group(2) or ""


def _normalize_metric(field_name: str, value: float, unit: str) -> tuple[float, str]:
    normalized_unit = unit.replace("m3", "m³").replace("hm2", "hm²").replace("m2", "m²")
    if field_name in {"disturbed_area", "land_area", "prevention_responsibility_area", "zone_area"}:
        if normalized_unit in {"亩"}:
            return value / 15, "hm²"
        if normalized_unit in {"m²", "平方米"}:
            return value / 10000, "hm²"
        return value, "hm²" if normalized_unit in {"hm²", "公顷", ""} else normalized_unit
    if field_name in {"excavation_volume", "fill_volume", "borrow_volume", "spoil_volume"}:
        if normalized_unit in {"m³", "立方米"}:
            return value / 10000, "万m³"
        return value, "万m³" if normalized_unit in {"万m³", "万立方米", ""} else normalized_unit
    if field_name == "investment_estimate":
        if normalized_unit == "亿元":
            return value * 10000, "万元"
        if normalized_unit == "元":
            return value / 10000, "万元"
        return value, "万元" if normalized_unit in {"万元", ""} else normalized_unit
    return value, normalized_unit


def _confidence(attrs: dict[str, Any], has_interval: bool, has_bbox: bool) -> int:
    try:
        return max(0, min(100, int(str(attrs.get("confidence", "")).strip())))
    except ValueError:
        return 86 if has_interval and has_bbox else 74 if has_interval else 62


def _source_text(text: str, value: str, start: int | None, end: int | None) -> str:
    if start is None or end is None:
        found = text.find(value)
        if found < 0:
            return value
        start = found
        end = found + len(value)
    return text[max(0, start - 80) : min(len(text), end + 80)].strip()


def _empty_field(name: str) -> dict[str, Any]:
    return {
        "field_name": name,
        "value": "",
        "normalized_value": "",
        "source_span": None,
        "section": "",
        "confidence": 35,
    }


def _facts_by_field(facts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_field: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_field.setdefault(_normalize_field_name(str(fact.get("field_name", ""))), []).append(fact)
    return by_field


def _best_numeric_fact(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    numeric = [fact for fact in facts if _numeric(fact) is not None]
    if not numeric:
        return None
    return sorted(numeric, key=lambda fact: int(fact.get("confidence") or 0), reverse=True)[0]


def _numeric(fact: dict[str, Any]) -> float | None:
    raw = str(fact.get("normalized_value") or fact.get("value") or "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _differs(left: float, right: float, tolerance: float) -> bool:
    base = max(abs(left), abs(right), 1.0)
    return abs(left - right) > base * tolerance


def _dedupe_facts(facts: list[EvidenceFact]) -> list[EvidenceFact]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EvidenceFact] = []
    for fact in facts:
        key = (fact.field_name, fact.normalized_value or fact.value, fact.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped


def _dedupe_findings(findings: list[CrossChapterFinding]) -> list[CrossChapterFinding]:
    seen: set[str] = set()
    deduped: list[CrossChapterFinding] = []
    for finding in findings:
        key = f"{finding.finding_type}:{finding.field_name}:{','.join(finding.fact_ids)}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _document_id(document: Any) -> str:
    value = getattr(document, "document_id", None)
    if value:
        return str(value)
    return str(getattr(document, "_document_id", "") or "")


def _chunk_text(chunk: Any) -> str:
    return str(getattr(chunk, "text", "") or "")


def _chunk_id(chunk: Any) -> str:
    return str(getattr(chunk, "chunk_id", "") or "")
