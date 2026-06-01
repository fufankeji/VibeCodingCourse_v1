"""
水土保持方案评审 LangGraph 工作流图构建

图结构：
START → scanning_node → routing_node → human_review_node → resume_check_node → report_generation_node → END

条件路由（routing_node 后）：
- "auto_pass" → 跳过 human_review_node → resume_check_node → report_generation_node
- "interrupt" / "batch_review" → human_review_node → resume_check_node → report_generation_node
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from app.workflow.state import ContractReviewState
from app.workflow.nodes import (
    scanning_node,
    routing_node,
    human_review_node,
    resume_check_node,
    report_generation_node,
    route_after_routing,
)

# 全局单例 checkpointer（InMemorySaver 用于开发）
_checkpointer = InMemorySaver()
_compiled_graph = None


def build_graph() -> StateGraph:
    """构建 StateGraph"""
    builder = StateGraph(ContractReviewState)

    # 添加所有节点
    builder.add_node("scanning_node", scanning_node)
    builder.add_node("routing_node", routing_node)
    builder.add_node("human_review_node", human_review_node)
    builder.add_node("resume_check_node", resume_check_node)
    builder.add_node("report_generation_node", report_generation_node)

    # 添加边
    builder.add_edge(START, "scanning_node")
    builder.add_edge("scanning_node", "routing_node")

    # routing_node 后的条件路由
    builder.add_conditional_edges(
        "routing_node",
        route_after_routing,
        {
            "auto_pass": "resume_check_node",      # 无风险，跳过人工审核
            "batch_review": "human_review_node",   # 中风险，批量审核
            "interrupt": "human_review_node",       # 高风险，逐条审核
        }
    )

    # human_review_node → resume_check_node（总是进入检查）
    builder.add_edge("human_review_node", "resume_check_node")

    # resume_check_node → report_generation_node
    builder.add_edge("resume_check_node", "report_generation_node")

    # 报告生成后结束
    builder.add_edge("report_generation_node", END)

    return builder


def get_compiled_graph():
    """
    获取已编译的图（单例模式）
    使用 InMemorySaver checkpointer 支持 interrupt/resume
    """
    global _compiled_graph
    if _compiled_graph is None:
        builder = build_graph()
        _compiled_graph = builder.compile(checkpointer=_checkpointer)
    return _compiled_graph


def get_checkpointer():
    """获取 checkpointer 实例（供 hitl_service 使用）"""
    return _checkpointer


def run_workflow_sync(
    session_id: str,
    contract_id: str,
    full_text: str,
    thread_id: str,
    precomputed_review_items: list[dict] | None = None,
) -> dict:
    """
    同步运行工作流（从 scanning_node 开始）

    调用时机：OCR 完成后，由 upload_service 触发

    Args:
        session_id: ReviewSession.id
        contract_id: Contract.id
        full_text: OCR 提取的方案全文
        thread_id: ReviewSession.langgraph_thread_id（作为 LangGraph thread_id）

    Returns:
        工作流最终状态
    """
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "session_id": session_id,
        "contract_id": contract_id,
        "langgraph_thread_id": thread_id,
        "full_text": full_text,
        "pages": [],
        "review_items": precomputed_review_items or [],
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "low_risk_count": 0,
        "route_result": "",
        "pending_item_ids": [],
        "human_decisions": None,
        "report_id": None,
        "error": None,
        "error_node": None,
    }

    # 调用图（会在 interrupt 处暂停）
    result = graph.invoke(initial_state, config)
    return result


def resume_workflow(thread_id: str, decisions_payload: list) -> dict:
    """
    恢复被 interrupt 的工作流

    调用时机：所有高风险条款决策完成后，由 hitl_service 触发

    Args:
        thread_id: ReviewSession.langgraph_thread_id
        decisions_payload: 人工决策列表

    Returns:
        工作流恢复后的最终状态
    """
    from langgraph.types import Command
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(Command(resume=decisions_payload), config)
    return result


def get_workflow_state(thread_id: str) -> dict:
    """
    查询工作流当前状态（用于跨天恢复）

    Returns:
        当前 checkpoint 的状态快照
    """
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    state = graph.get_state(config)
    return state
