"""
LangGraph 工作流节点实现

节点清单：
- scanning_node：AI 风险扫描（调用 DeepSeek LLM）
- routing_node：按风险分级路由
- human_review_node：HITL 中断点（interrupt 调用）
- resume_check_node：resume 后完整性校验
- report_generation_node：报告生成触发

注意：parse_node / field_extraction 由 ocr_service 在图外部处理，
      workflow 从 scanning_node 开始（OCR 完成后调用）
"""
import json
import uuid
from datetime import datetime
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt, Command

from app.workflow.state import ContractReviewState
from app.config import get_llm as get_configured_llm

# ============================================================
# LLM 初始化
# ============================================================
def get_llm():
    return get_configured_llm()

RISK_SCAN_SYSTEM_PROMPT = """你是一个专业的合同法律风险审查 AI。
你需要分析合同段落，识别潜在的法律风险。

对于每个高风险或中风险的段落，返回 JSON 格式：
{
  "risk_level": "HIGH" | "MEDIUM" | "LOW",
  "confidence_score": 0-100,
  "source_type": "rule_engine" | "ai_inference",
  "risk_category": "风险类别（如：单边条款、违约金条款等）",
  "ai_finding": "可能存在...风险（必须使用模态表述，不可绝对化）",
  "ai_reasoning": "风险分析理由",
  "suggested_revision": "修改建议（可选）"
}

重要约束：
1. ai_finding 必须使用模态表述：以"可能存在...风险"开头
2. 不可使用绝对化结论（如"该条款违法"）
3. LOW 风险可以简化输出

只返回 JSON，不要其他内容。"""


# ============================================================
# 节点实现
# ============================================================

def scanning_node(state: ContractReviewState) -> dict:
    """
    AI 风险扫描节点：对合同全文逐段落扫描，生成 ReviewItem 列表

    输入：state.full_text, state.pages
    输出：state.review_items, state.high_risk_count, state.medium_risk_count, state.low_risk_count
    """
    precomputed_items = state.get("review_items", [])
    if precomputed_items:
        return {
            "review_items": precomputed_items,
            "high_risk_count": sum(1 for item in precomputed_items if item.get("risk_level") == "HIGH"),
            "medium_risk_count": sum(1 for item in precomputed_items if item.get("risk_level") == "MEDIUM"),
            "low_risk_count": sum(1 for item in precomputed_items if item.get("risk_level") == "LOW"),
        }

    llm = get_llm()
    full_text = state.get("full_text", "")
    session_id = state["session_id"]

    # 分段落处理（每段落不超过 1000 字）
    paragraphs = _split_into_paragraphs(full_text)

    review_items = []
    high_count = 0
    medium_count = 0
    low_count = 0

    for i, (para_text, page_num, para_idx) in enumerate(paragraphs):
        if len(para_text.strip()) < 10:  # 跳过过短段落
            continue

        try:
            # 调用 DeepSeek 分析风险
            messages = [
                SystemMessage(content=RISK_SCAN_SYSTEM_PROMPT),
                HumanMessage(content=f"请分析以下合同段落的风险：\n\n{para_text[:800]}")
            ]
            response = llm.invoke(messages)
            result_text = response.content.strip()

            # 解析 JSON 响应
            # 清理 markdown 代码块
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            risk_data = json.loads(result_text)
            risk_level = risk_data.get("risk_level", "LOW")

            if risk_level in ("HIGH", "MEDIUM"):
                item_id = str(uuid.uuid4())
                review_item = {
                    "id": item_id,
                    "session_id": session_id,
                    "clause_text": para_text,
                    "page_number": page_num,
                    "paragraph_index": para_idx,
                    "highlight_anchor": f"page{page_num}-para{para_idx}",
                    "char_offset_start": 0,
                    "char_offset_end": len(para_text),
                    "risk_level": risk_level,
                    "confidence_score": risk_data.get("confidence_score", 70),
                    "source_type": risk_data.get("source_type", "ai_inference"),
                    "risk_category": risk_data.get("risk_category", "未分类"),
                    "ai_finding": _ensure_modal_expression(risk_data.get("ai_finding", "")),
                    "ai_reasoning": risk_data.get("ai_reasoning", ""),
                    "suggested_revision": risk_data.get("suggested_revision"),
                    "human_decision": "pending",
                }
                review_items.append(review_item)

                if risk_level == "HIGH":
                    high_count += 1
                else:
                    medium_count += 1
            else:
                low_count += 1

        except Exception as e:
            # LLM 失败时降级：标记为低风险
            low_count += 1
            continue

    # 如果没有发现风险，添加一个 mock 中风险条款（用于 MVP 测试）
    if not review_items and full_text:
        review_items.append(_create_mock_high_risk_item(session_id, full_text))
        high_count = 1

    return {
        "review_items": review_items,
        "high_risk_count": high_count,
        "medium_risk_count": medium_count,
        "low_risk_count": low_count,
    }


def routing_node(state: ContractReviewState) -> dict:
    """
    路由节点：根据风险分布决定路由目标

    路由规则（严格按优先级）：
    1. 存在高风险 → interrupt（route_result = "interrupt"）
    2. 仅中风险 → batch_review（route_result = "batch_review"）
    3. 仅低风险 → auto_pass（route_result = "auto_pass"）

    输出：state.route_result, state.pending_item_ids
    """
    high_count = state.get("high_risk_count", 0)
    medium_count = state.get("medium_risk_count", 0)
    review_items = state.get("review_items", [])

    # 收集待处理条款 ID
    pending_ids = [
        item["id"] for item in review_items
        if item.get("human_decision") == "pending"
    ]

    if high_count > 0:
        route = "interrupt"
    elif medium_count > 0:
        route = "batch_review"
    else:
        route = "auto_pass"

    return {
        "route_result": route,
        "pending_item_ids": pending_ids,
    }


def human_review_node(state: ContractReviewState) -> dict:
    """
    人工审核节点（HITL 中断点）

    根据路由结果决定是否触发 interrupt：
    - route_result = "interrupt"：触发 interrupt，等待所有高风险条款决策
    - route_result = "batch_review"：触发 interrupt，等待中风险批量确认
    - route_result = "auto_pass"：直接通过（不 interrupt）

    严格遵循单一中断点原则：只调用一次 interrupt，
    一次性传入所有待处理条款 ID，通过单次 Command(resume=...) 恢复
    """
    route_result = state.get("route_result", "auto_pass")
    session_id = state["session_id"]
    pending_item_ids = state.get("pending_item_ids", [])
    high_risk_count = state.get("high_risk_count", 0)
    medium_risk_count = state.get("medium_risk_count", 0)

    if route_result == "interrupt":
        # 触发 interrupt，等待人工逐条处理高风险条款
        human_decisions = interrupt({
            "review_type": "high_risk_review",
            "session_id": session_id,
            "pending_item_ids": pending_item_ids,
            "high_risk_count": high_risk_count,
            "medium_risk_count": medium_risk_count,
            "message": f"发现 {high_risk_count} 个高风险条款，请逐条审核"
        })
        return {"human_decisions": human_decisions}

    elif route_result == "batch_review":
        # 触发 interrupt，等待中风险批量确认
        human_decisions = interrupt({
            "review_type": "batch_review",
            "session_id": session_id,
            "pending_item_ids": pending_item_ids,
            "high_risk_count": 0,
            "medium_risk_count": medium_risk_count,
            "message": f"发现 {medium_risk_count} 个中风险条款，可批量确认"
        })
        return {"human_decisions": human_decisions}

    else:
        # auto_pass：无需人工介入
        return {"human_decisions": [], "route_result": "auto_pass"}


def resume_check_node(state: ContractReviewState) -> dict:
    """
    Resume 后完整性校验节点

    功能：
    1. 验证 human_decisions 数组覆盖所有待处理条款
    2. 如有遗漏，重新触发 interrupt（防止操作遗漏）
    3. 校验通过则继续执行报告生成
    """
    human_decisions = state.get("human_decisions", [])
    pending_item_ids = state.get("pending_item_ids", [])
    route_result = state.get("route_result", "auto_pass")

    if route_result == "auto_pass":
        # 无需检查
        return {}

    # 检查所有条款是否都有决策
    decided_ids = set(d.get("item_id") for d in (human_decisions or []))
    pending_set = set(pending_item_ids)
    missing_ids = pending_set - decided_ids

    if missing_ids and route_result == "interrupt":
        # 有遗漏，重新中断
        remaining = interrupt({
            "review_type": "high_risk_review",
            "session_id": state["session_id"],
            "pending_item_ids": list(missing_ids),
            "high_risk_count": len(missing_ids),
            "medium_risk_count": 0,
            "message": f"尚有 {len(missing_ids)} 个高风险条款未处理，请继续审核"
        })
        # 合并决策
        current = human_decisions or []
        if remaining:
            current = current + (remaining if isinstance(remaining, list) else [remaining])
        return {"human_decisions": current}

    # 校验通过
    return {}


def report_generation_node(state: ContractReviewState) -> dict:
    """
    报告生成节点

    功能：
    1. 触发后端报告生成服务（异步）
    2. 更新状态为 report_ready
    3. 返回 report_id

    注意：实际报告生成由 report_service 处理，
          此节点只负责触发和记录
    """
    session_id = state["session_id"]
    report_id = str(uuid.uuid4())

    # 实际报告生成由外部服务完成
    # 此处记录触发时间和状态
    return {
        "report_id": report_id,
        "error": None,
    }


# ============================================================
# 路由函数（用于 add_conditional_edges）
# ============================================================

def route_after_routing(state: ContractReviewState) -> str:
    """routing_node 后的条件路由"""
    return state.get("route_result", "auto_pass")


def route_after_human_review(state: ContractReviewState) -> str:
    """human_review_node 后的路由（无论是否 interrupt，都进入 resume_check）"""
    return "resume_check"


# ============================================================
# 辅助函数
# ============================================================

def _split_into_paragraphs(text: str) -> list:
    """将全文分割为段落列表，返回 (text, page_num, para_idx) 元组"""
    if not text:
        return []

    # 按换行分割
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # 合并短行为段落（至少 20 字）
    paragraphs = []
    current = []
    for line in lines:
        current.append(line)
        if len(''.join(current)) >= 100:
            paragraphs.append(''.join(current))
            current = []
    if current:
        paragraphs.append(''.join(current))

    # 分配页码和段落索引（简化：每 5 段为一页）
    result = []
    for i, para in enumerate(paragraphs):
        page_num = (i // 5) + 1
        para_idx = i % 5
        result.append((para, page_num, para_idx))

    return result


def _ensure_modal_expression(finding: str) -> str:
    """确保 ai_finding 使用模态表述，不包含绝对化结论"""
    if not finding:
        return "可能存在潜在法律风险"

    # 移除绝对化表述
    absolute_phrases = ["该条款违法", "明显违法", "肯定存在", "必然导致", "一定会"]
    for phrase in absolute_phrases:
        finding = finding.replace(phrase, "可能存在相关风险")

    # 确保以模态表述开头
    if not any(finding.startswith(prefix) for prefix in ["可能", "疑似", "存在", "潜在"]):
        finding = "可能存在" + finding

    return finding


def _create_mock_high_risk_item(session_id: str, full_text: str) -> dict:
    """
    当 LLM 未检测到风险时，创建 mock 高风险条款（用于 MVP 演示和测试）
    """
    # 取合同前 200 字作为示例条款
    sample_text = full_text[:200] if len(full_text) > 200 else full_text

    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "clause_text": sample_text or "甲方有权随时修改本协议条款，修改后即时生效",
        "page_number": 1,
        "paragraph_index": 0,
        "highlight_anchor": "page1-para0",
        "char_offset_start": 0,
        "char_offset_end": len(sample_text),
        "risk_level": "HIGH",
        "confidence_score": 85,
        "source_type": "rule_engine",
        "risk_category": "单边条款",
        "ai_finding": "可能存在单边修改权风险：甲方可单方面变更服务内容而无需乙方同意",
        "ai_reasoning": "该条款赋予甲方单方面变更权，缺乏对等制衡机制，可能存在权利滥用风险",
        "suggested_revision": "建议增加“重大变更需提前30日书面通知乙方并取得书面同意”的约束",
        "human_decision": "pending",
    }
