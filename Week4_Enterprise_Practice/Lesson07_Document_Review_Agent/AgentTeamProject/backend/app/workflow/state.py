from typing import TypedDict, Optional, List, Any
from typing_extensions import Annotated
import operator


class ContractReviewState(TypedDict):
    """水土保持方案评审 LangGraph 状态"""
    session_id: str
    contract_id: str
    langgraph_thread_id: str

    # OCR 解析输出
    full_text: str                    # 方案全文
    pages: List[dict]                 # 分页文本列表 [{page_num, text, paragraphs}]

    # 风险扫描结果
    review_items: List[dict]          # ReviewItem 数据（写入 DB 后的结果）
    high_risk_count: int              # 高风险条款数
    medium_risk_count: int            # 中风险条款数
    low_risk_count: int               # 低风险条款数

    # 路由结果
    route_result: str                 # "auto_pass" / "batch_review" / "interrupt"
    pending_item_ids: List[str]       # 待处理的条款 ID 列表

    # HITL 决策（resume 后注入）
    human_decisions: Optional[List[dict]]   # 人工决策列表

    # 报告
    report_id: Optional[str]

    # 错误状态
    error: Optional[str]
    error_node: Optional[str]
