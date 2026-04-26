"""
Report Service — generate and persist review reports.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.core.sse import sse_manager
from app.models.audit_log import AuditLog
from app.models.extracted_field import ExtractedField
from app.models.report import ReviewReport
from app.models.review_item import ReviewItem
from app.models.session import ReviewSession
from app.schemas.report import ReviewReportResponse

_DISCLAIMER = (
    "本审查意见稿由智能辅助系统基于已解析文本、规则库和问题清单生成，"
    "仅供水土保持方案技术审查参考，最终意见以人工复核和主管部门要求为准。"
)

_COVERAGE_STATEMENT = {
    "scope": "本次审核基于 MinerU 解析文本、bbox 坐标块和水土保持方案审查规则集。",
    "covered_clause_types": ["形式完整性", "项目概况", "工程占地", "土石方平衡", "表土保护", "弃渣去向", "监测与投资"],
    "not_covered_clause_types": ["图片内容细审", "附图几何量测", "外部批复文件真实性核验"],
    "limitations": [
        "解析结果依赖既有 MinerU 输出，扫描识别误差会影响命中结果",
        "本版未做图片审查和附图空间关系量测",
        "规则命中结果需要业务人员复核后形成正式意见",
    ],
    "confidence_note": "置信度反映规则命中和证据召回确定性，不代表最终审查结论",
}


def generate_report_sync(session_id: str, db: Session) -> None:
    """Synchronous wrapper for report generation (used from background threads)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context — schedule as a task
            import concurrent.futures
            future = concurrent.futures.Future()

            async def _run():
                try:
                    result = await generate_report(session_id, db)
                    future.set_result(result)
                except Exception as e:
                    future.set_exception(e)

            asyncio.ensure_future(_run())
            return
        else:
            loop.run_until_complete(generate_report(session_id, db))
    except RuntimeError:
        # No event loop in this thread — create one
        asyncio.run(generate_report(session_id, db))


async def generate_report(session_id: str, db: Session) -> ReviewReportResponse:
    session: ReviewSession | None = db.query(ReviewSession).filter(ReviewSession.id == session_id).first()
    if not session:
        from app.core.errors import APIError
        raise APIError.not_found("ReviewSession")

    # Aggregate data
    items = db.query(ReviewItem).filter(ReviewItem.session_id == session_id).all()
    fields = db.query(ExtractedField).filter(ExtractedField.session_id == session_id).all()

    # Item statistics
    item_stats = _compute_item_stats(items)

    # Build summary
    summary = _build_summary(session, items, fields, item_stats)

    # Create or update report record
    report = db.query(ReviewReport).filter(ReviewReport.session_id == session_id).first()
    now = datetime.utcnow()
    if not report:
        report = ReviewReport(session_id=session_id)
        db.add(report)

    report.report_status = "generating"
    report.summary_json = json.dumps(summary, ensure_ascii=False)
    report.item_stats_json = json.dumps(item_stats, ensure_ascii=False)
    report.coverage_statement_json = json.dumps(_COVERAGE_STATEMENT, ensure_ascii=False)
    report.disclaimer = _DISCLAIMER
    db.commit()
    db.refresh(report)

    # Persist JSON report to storage
    report_dir = Path(settings.storage_path) / "reports" / session_id
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = str(report_dir / "report.json")

    full_report = {
        "report_id": report.id,
        "session_id": session_id,
        "generated_at": now.isoformat(),
        "summary": summary,
        "item_stats": item_stats,
        "coverage_statement": _COVERAGE_STATEMENT,
        "disclaimer": _DISCLAIMER,
        "items": [_serialize_item(i) for i in items],
        "fields": [_serialize_field(f) for f in fields],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2, default=str)

    # Update report record as ready
    report.report_status = "ready"
    report.generated_at = now
    report.json_path = json_path
    db.add(report)

    # Update session state
    session.state = "report_ready"
    session.completed_at = now
    session.updated_at = now
    db.add(session)

    # Audit log
    audit = AuditLog(
        session_id=session_id,
        event_type="report_generated",
        actor_id="system",
        actor_type="system",
        occurred_at=now,
        metadata_json=json.dumps({"json_path": json_path}),
    )
    db.add(audit)
    db.commit()
    db.refresh(report)

    # SSE push
    await sse_manager.publish(
        session_id,
        "report_ready",
        {"session_id": session_id, "report_id": report.id},
    )

    return ReviewReportResponse.model_validate(report)


def _compute_item_stats(items: list[ReviewItem]) -> dict:
    total = len(items)
    high = sum(1 for i in items if i.risk_level == "HIGH")
    medium = sum(1 for i in items if i.risk_level == "MEDIUM")
    low = sum(1 for i in items if i.risk_level == "LOW")
    confirmed = sum(1 for i in items if i.human_decision == "confirmed")
    rejected = sum(1 for i in items if i.human_decision == "rejected")
    false_positive = sum(1 for i in items if i.is_false_positive)
    pending = sum(1 for i in items if i.human_decision == "pending")

    return {
        "total": total,
        "approved": confirmed,
        "edited": sum(1 for i in items if i.human_decision == "edit"),
        "rejected": rejected + false_positive,
        "auto_passed": low,
        "by_risk": {"HIGH": high, "MEDIUM": medium, "LOW": low},
        "by_decision": {
            "confirmed": confirmed,
            "rejected": rejected,
            "false_positive": false_positive,
            "pending": pending,
        },
    }


def _build_summary(
    session: ReviewSession,
    items: list[ReviewItem],
    fields: list[ExtractedField],
    stats: dict,
) -> dict:
    high_count = stats["by_risk"]["HIGH"]
    medium_count = stats["by_risk"]["MEDIUM"]

    field_map = {field.field_name: field.field_value for field in fields}

    if high_count >= 3:
        risk_conclusion = "方案存在多项需重点复核的问题，建议按问题清单补充材料并复核相关章节。"
    elif high_count >= 1:
        risk_conclusion = "方案存在重点问题，建议优先核查高风险问题对应证据和规则依据。"
    elif medium_count >= 3:
        risk_conclusion = "方案存在若干一般问题，建议结合材料完整性进行修订。"
    else:
        risk_conclusion = "首版规则未发现明显高风险问题，仍建议人工抽查关键字段与附图附表。"

    return {
        "project_name": field_map.get("project_name", ""),
        "construction_unit": field_map.get("construction_unit", ""),
        "project_location": field_map.get("project_location") or field_map.get("construction_location", ""),
        "construction_nature": field_map.get("construction_nature") or field_map.get("project_nature", ""),
        "investment_estimate": field_map.get("investment_estimate", ""),
        "contract_parties": [field_map.get("construction_unit", "")],
        "contract_amount": field_map.get("investment_estimate", ""),
        "effective_date": "",
        "overall_risk_level": "high" if high_count else "medium" if medium_count else "low",
        "conclusion": risk_conclusion,
        "risk_conclusion": risk_conclusion,
        "total_issues": stats["total"],
        "high_risk_count": high_count,
        "medium_risk_count": medium_count,
        "low_risk_count": stats["by_risk"]["LOW"],
        "field_extraction_count": len(fields),
        "session_state": session.state,
        "opinion_draft": _build_opinion_draft(items),
    }


def _serialize_item(item: ReviewItem) -> dict:
    return {
        "id": item.id,
        "clause_text": item.clause_text,
        "risk_level": item.risk_level,
        "risk_category": item.risk_category,
        "ai_finding": item.ai_finding,
        "human_decision": item.human_decision,
        "human_note": item.human_note,
        "is_false_positive": item.is_false_positive,
        "page_number": item.page_number,
        "suggested_revision": item.suggested_revision,
    }


def _serialize_field(field: ExtractedField) -> dict:
    return {
        "id": field.id,
        "field_name": field.field_name,
        "field_value": field.field_value,
        "confidence_score": field.confidence_score,
        "verification_status": field.verification_status,
    }


def _build_opinion_draft(items: list[ReviewItem]) -> str:
    pending = [item for item in items if item.human_decision == "pending"]
    grouped: dict[str, list[ReviewItem]] = {}
    for item in pending:
        grouped.setdefault(item.risk_category or "其他问题", []).append(item)

    lines = ["水土保持方案审查意见稿（智能辅助生成）", ""]
    if not pending:
        lines.append("经规则库辅助核查，当前问题均已处理。建议结合人工复核意见形成正式审查结论。")
        return "\n".join(lines)

    lines.append("经对方案文本、结构化字段和规则库命中结果进行核查，建议重点关注以下问题：")
    for category, category_items in grouped.items():
        lines.append(f"\n{category}：")
        for index, item in enumerate(category_items[:5], start=1):
            lines.append(f"{index}. {item.ai_finding} 建议：{item.suggested_revision or '请补充说明并复核。'}")
    lines.append("\n以上意见需结合原文证据、附件附图及业务人员复核结果后定稿。")
    return "\n".join(lines)
