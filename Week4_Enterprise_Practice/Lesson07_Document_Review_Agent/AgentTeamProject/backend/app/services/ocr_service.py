"""
Document parsing service.

For the water-soil conservation MVP, this service consumes the prepared MinerU
JSON and rule set in backend/data, persists extracted fields, and hands
precomputed issues to the existing LangGraph/HITL flow.
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.sse import sse_manager
from app.models.audit_log import AuditLog
from app.models.extracted_field import ExtractedField
from app.models.session import ReviewSession

STRUCTURED_FIELDS = [
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

logger = logging.getLogger(__name__)


def classify_pipeline_failure(error_message: str) -> dict[str, str]:
    raw = (error_message or "").strip()
    normalized = raw.lower()
    if "no grounded facts" in normalized:
        return {
            "failure_category": "evidence_insufficient",
            "user_message": (
                "证据不足：当前解析结果未抽取到可用于字段核验和规则审查的原文证据。"
                "常见原因是文档不是水土保持方案、内容过少、扫描识别质量差，或关键章节/指标缺失。"
            ),
        }
    if "review_llm_api_key" in normalized or "deepseek_api_key" in normalized:
        return {
            "failure_category": "llm_config_missing",
            "user_message": "缺少大模型配置：后端未配置 REVIEW_LLM_API_KEY 或 DEEPSEEK_API_KEY，无法执行证据抽取。",
        }
    if "siliconflow_api_key" in normalized:
        return {
            "failure_category": "vector_config_missing",
            "user_message": "缺少向量服务配置：后端未配置 SILICONFLOW_API_KEY，无法创建向量索引或召回证据。",
        }
    if "extraction failed for all documents" in normalized:
        return {
            "failure_category": "evidence_extraction_failed",
            "user_message": "证据抽取服务失败：所有候选文档片段都未完成抽取，请查看后端日志中的 LangExtract 错误。",
        }
    if "langextract package is not available" in normalized or "langextract openai provider is not available" in normalized:
        return {
            "failure_category": "langextract_dependency_missing",
            "user_message": "证据抽取依赖缺失：后端运行环境缺少 LangExtract 或其 OpenAI provider。",
        }
    if "siliconflow" in normalized or "embedding" in normalized or "reranker" in normalized or "vector retrieval failed" in normalized:
        return {
            "failure_category": "vector_service_failed",
            "user_message": "向量服务异常：向量生成、召回或重排失败，请检查 SiliconFlow 返回、网络和向量库状态。",
        }
    if "deepseek" in normalized or "adjudication" in normalized or "json object" in normalized:
        return {
            "failure_category": "review_llm_failed",
            "user_message": "规则审查模型调用失败：LLM 判定阶段返回异常或格式不符合要求。",
        }
    return {
        "failure_category": "pipeline_runtime_error",
        "user_message": "数据清洗与向量审查运行异常，请查看后端日志定位具体堆栈。",
    }

# Prompts
_EXTRACTION_SYSTEM = """你是一名水土保持方案技术审查助手。请从以下方案文本中提取结构化字段信息。
返回严格的 JSON 对象，包含以下键（如未找到则返回空字符串）：
project_name, construction_unit, construction_location, project_nature, disturbed_area, land_area, investment_estimate

示例输出：
{
  "project_name": "某水土保持方案项目",
  "construction_unit": "某建设单位",
  "construction_location": "某市某区",
  "project_nature": "新建",
  "disturbed_area": "1.5hm²",
  "land_area": "3hm²",
  "investment_estimate": "16万元"
}
只返回 JSON，不要其他内容。"""


def extract_text(file_path: str) -> str:
    """Extract raw text from a PDF or DOCX file."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf_text(file_path)
    elif suffix == ".docx":
        return _extract_docx_text(file_path)
    else:
        return ""


def _extract_pdf_text(file_path: str) -> str:
    try:
        import PyPDF2

        text_parts = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except Exception:
        return ""


def _extract_docx_text(file_path: str) -> str:
    try:
        from docx import Document

        doc = Document(file_path)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except Exception:
        return ""


async def extract_fields(session_id: str, text: str, db: Session, file_path: str | None = None) -> dict | None:
    """Extract water-soil fields, persist them, and trigger review workflow."""
    # Update session state to scanning
    session: ReviewSession | None = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        return None

    previous_state = session.state
    session.state = "scanning"
    session.updated_at = datetime.utcnow()
    db.add(session)
    db.commit()

    await sse_manager.publish(
        session_id,
        "state_changed",
        {"session_id": session_id, "state": "scanning"},
    )

    pipeline: dict | None = None
    contract_id = session.contract_id
    artifact_dir = str(Path(file_path).parent / "water_review") if file_path else f"./storage/contracts/{contract_id}/water_review"
    logger.info(
        "water_review_pipeline_start session_id=%s contract_id=%s previous_state=%s file_path=%s artifact_dir=%s",
        session_id,
        contract_id,
        previous_state,
        file_path or "",
        artifact_dir,
    )
    try:
        from app.services import water_review_service

        pipeline = await asyncio.to_thread(water_review_service.run_pipeline, file_path or "", artifact_dir, session_id)
        text = pipeline.get("full_text") or text
        extracted_fields = pipeline.get("fields", [])
    except Exception as exc:
        error_message = str(exc)
        failure_state = "parsed" if previous_state == "parsed" else "aborted"
        failure = classify_pipeline_failure(error_message)
        logger.exception(
            "water_review_pipeline_failed session_id=%s contract_id=%s previous_state=%s failure_state=%s "
            "file_path=%s artifact_dir=%s error_code=RAG_REVIEW_FAILED failure_category=%s user_message=%s error=%s",
            session_id,
            contract_id,
            previous_state,
            failure_state,
            file_path or "",
            artifact_dir,
            failure["failure_category"],
            failure["user_message"],
            error_message,
        )
        session.state = failure_state
        session.updated_at = datetime.utcnow()
        db.add(session)
        db.add(
            AuditLog(
                session_id=session_id,
                event_type="system_failure",
                actor_id="system",
                actor_type="system",
                metadata_json=json.dumps(
                    {
                        "error": error_message,
                        "error_code": "RAG_REVIEW_FAILED",
                        "node_name": "water_review_rag_pipeline",
                        "exception_type": exc.__class__.__name__,
                        "failure_category": failure["failure_category"],
                        "user_message": failure["user_message"],
                        "file_path": file_path or "",
                        "artifact_dir": artifact_dir,
                        "previous_state": previous_state,
                        "failure_state": failure_state,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        await sse_manager.publish(
            session_id,
            "system_failure",
            {
                "session_id": session_id,
                "state": failure_state,
                "error_code": "RAG_REVIEW_FAILED",
                "message": failure["user_message"],
                "technical_message": error_message,
                "failure_category": failure["failure_category"],
                "node_name": "water_review_rag_pipeline",
            },
        )
        return None

    db.query(ExtractedField).filter(ExtractedField.session_id == session_id).delete()

    # Persist each field
    for data in extracted_fields:
        field_name = data.get("field_name", "")
        if field_name not in STRUCTURED_FIELDS:
            continue
        value = data.get("value", "")
        confidence = int(data.get("confidence") or random.randint(40, 99))
        needs_verification = confidence < 60
        source_span = data.get("source_span") or {}

        field = ExtractedField(
            session_id=session_id,
            field_name=field_name,
            field_value=value,
            original_value=data.get("normalized_value") or value,
            confidence_score=confidence,
            needs_human_verification=needs_verification,
            verification_status="unverified",
            source_evidence_text=data.get("source_evidence_text") or _find_evidence(text, value),
            source_page_number=int(data.get("source_page_number") or 1),
            source_char_offset_start=source_span.get("char_start", 0),
            source_char_offset_end=source_span.get("char_end", 0),
        )
        db.add(field)

    db.commit()

    # Write audit log
    audit = AuditLog(
        session_id=session_id,
        event_type="fields_extracted",
        actor_id="system",
        actor_type="system",
        metadata_json=json.dumps({"field_count": len(STRUCTURED_FIELDS)}),
    )
    db.add(audit)
    db.commit()

    await sse_manager.publish(
        session_id,
        "fields_extracted",
        {"session_id": session_id, "field_count": len(STRUCTURED_FIELDS)},
    )

    # Trigger LangGraph workflow if available
    await _trigger_workflow(
        session_id,
        text,
        db,
        precomputed_review_items=(pipeline or {}).get("review_items", []),
    )
    return pipeline


async def _llm_extract_fields(text: str) -> dict[str, str]:
    from app.config import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm()
    # Truncate to avoid token limits
    truncated = text[:8000] if len(text) > 8000 else text
    messages = [
        SystemMessage(content=_EXTRACTION_SYSTEM),
        HumanMessage(content=f"水土保持方案文本：\n\n{truncated}"),
    ]
    response = await llm.ainvoke(messages)
    content = response.content.strip()
    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
    return json.loads(content)


def _find_evidence(text: str, value: str) -> str:
    """Return a short surrounding snippet as evidence."""
    if not value or not text:
        return ""
    idx = text.find(value)
    if idx == -1:
        return ""
    start = max(0, idx - 50)
    end = min(len(text), idx + len(value) + 50)
    return text[start:end]


async def _trigger_workflow(
    session_id: str,
    text: str,
    db: Session,
    precomputed_review_items: list[dict] | None = None,
) -> None:
    """Trigger LangGraph review workflow after OCR completes."""
    try:
        from app.services.hitl_service import hitl_service

        session: ReviewSession | None = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
        if not session:
            return

        thread_id = session.langgraph_thread_id

        # hitl_service.trigger_workflow_for_session handles:
        # 1. Updating session state to "scanning"
        # 2. Running workflow in background thread
        # 3. Persisting review items to DB
        # 4. Pushing SSE events
        hitl_service.trigger_workflow_for_session(
            session_id,
            thread_id,
            text,
            db,
            precomputed_review_items=precomputed_review_items,
        )
    except ImportError:
        # Workflow module not yet available; skip silently
        pass
