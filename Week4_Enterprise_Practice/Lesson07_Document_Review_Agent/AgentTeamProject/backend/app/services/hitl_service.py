"""
HITL 服务层

职责：
1. 检测 resume 触发条件（所有高风险条款已决策）
2. 触发 LangGraph resume（恢复被 interrupt 挂起的工作流）
3. 跨天恢复：从 Checkpointer 恢复工作流状态
4. 推送 SSE 事件通知前端
5. 触发报告生成

与 T1 (workflow) 的交互边界：
- hitl_service 调用 graph.py 的 resume_workflow() 和 get_workflow_state()
- hitl_service 不直接操作 LangGraph 内部状态
- 数据库是权威来源，Checkpointer 是辅助

与 T3 (API) 的交互边界：
- T3 的 review_service 在每次 HITL 决策成功后调用 check_and_trigger_resume()
- hitl_service 不直接处理 HTTP 请求
"""

import json
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.session import ReviewSession
from app.models.review_item import ReviewItem
from app.models.audit_log import AuditLog
from app.database import SessionLocal


class HITLService:
    """HITL 业务逻辑服务"""

    def check_and_trigger_resume(
        self,
        session_id: str,
        db: Session,
        actor_id: str = "system",
    ) -> bool:
        """
        检查是否满足 resume 触发条件，满足则触发 LangGraph resume。

        触发条件：所有 risk_level=HIGH 的 ReviewItem.human_decision != 'pending'

        Returns:
            True：已触发 resume
            False：条件未满足，不触发
        """
        session = db.query(ReviewSession).filter(
            ReviewSession.id == session_id
        ).first()

        if not session or session.state != "hitl_pending":
            return False

        # 检查所有高风险条款是否已决策
        pending_high_risk = db.query(ReviewItem).filter(
            ReviewItem.session_id == session_id,
            ReviewItem.risk_level == "HIGH",
            ReviewItem.human_decision == "pending",
        ).count()

        if pending_high_risk > 0:
            return False  # 还有未处理的高风险条款

        # 所有高风险条款已处理，触发 resume
        self._do_resume(session, db, actor_id)
        return True

    def _do_resume(self, session: ReviewSession, db: Session, actor_id: str):
        """
        执行 LangGraph resume 操作。

        执行序列：
        1. 从数据库收集所有高风险条款的决策
        2. 构造 decisions_payload
        3. 更新 session.state = "completed"
        4. 写入 AuditLog
        5. 提交数据库变更
        6. 在后台线程调用 resume_workflow()
        7. 推送 SSE 事件
        """
        try:
            # Step 1: 收集决策数据
            high_risk_items = db.query(ReviewItem).filter(
                ReviewItem.session_id == session.id,
                ReviewItem.risk_level == "HIGH",
            ).all()

            decisions_payload = [
                {
                    "item_id": item.id,
                    "decision": item.human_decision,
                    "note": item.human_note or "",
                    "edited_risk_level": item.human_edited_risk_level,
                    "edited_finding": item.human_edited_finding,
                    "is_false_positive": item.is_false_positive,
                }
                for item in high_risk_items
            ]

            # Step 2: 更新 session 状态为 completed
            session.state = "completed"
            session.updated_at = datetime.utcnow()

            # Step 3: 写入 AuditLog
            log = AuditLog(
                session_id=session.id,
                event_type="report_generation_started",
                actor_id=actor_id,
                actor_type="system",
                metadata_json=json.dumps({
                    "decisions_count": len(decisions_payload),
                    "triggered_at": datetime.utcnow().isoformat(),
                }),
            )
            db.add(log)
            db.commit()

            # Step 4: 在后台线程执行 workflow resume（不阻塞 API）
            thread_id = session.langgraph_thread_id
            session_id = session.id

            t = threading.Thread(
                target=self._resume_and_generate_report,
                args=(session_id, thread_id, decisions_payload),
                daemon=True,
            )
            t.start()

            # Step 5: 推送 SSE 事件（report_generation_started）
            self._push_sse_event(session_id, "report_generation_started", {
                "session_id": session_id,
            })

        except Exception as e:
            db.rollback()
            error_log = AuditLog(
                session_id=session.id,
                event_type="system_failure",
                actor_id="system",
                actor_type="system",
                metadata_json=json.dumps({
                    "error": str(e),
                    "node_name": "hitl_service._do_resume",
                }),
            )
            db.add(error_log)
            db.commit()
            raise

    def _resume_and_generate_report(
        self,
        session_id: str,
        thread_id: str,
        decisions_payload: list,
    ):
        """
        在后台线程中执行：
        1. 调用 LangGraph resume_workflow
        2. 生成报告
        3. 更新 session 状态为 report_ready（由 report_service 负责）
        """
        db = SessionLocal()
        try:
            from app.workflow.graph import resume_workflow
            resume_workflow(thread_id, decisions_payload)

            from app.services.report_service import generate_report_sync
            generate_report_sync(session_id, db)

        except Exception as e:
            # 记录错误审计日志
            db_err = SessionLocal()
            try:
                log = AuditLog(
                    session_id=session_id,
                    event_type="system_failure",
                    actor_id="system",
                    actor_type="system",
                    metadata_json=json.dumps({
                        "error": str(e),
                        "node_name": "_resume_and_generate_report",
                    }),
                )
                db_err.add(log)
                db_err.commit()
            finally:
                db_err.close()
        finally:
            db.close()

    def get_recovery_info(self, session_id: str, db: Session) -> dict:
        """
        获取跨天恢复信息。

        用于 GET /sessions/{session_id}/recovery 接口

        Returns:
            恢复信息字典，包含断点时间、已完成数、下一条待处理条款 ID
        """
        session = db.query(ReviewSession).filter(
            ReviewSession.id == session_id
        ).first()

        if not session or session.state != "hitl_pending":
            return {
                "session_id": session_id,
                "recovery_status": "not_applicable",
                "interrupted_at": None,
                "completed_count": 0,
                "total_high_risk_count": 0,
                "next_pending_item_id": None,
            }

        # 查询已决策的高风险条款数
        decided_count = db.query(ReviewItem).filter(
            ReviewItem.session_id == session_id,
            ReviewItem.risk_level == "HIGH",
            ReviewItem.human_decision != "pending",
        ).count()

        total_high_risk = db.query(ReviewItem).filter(
            ReviewItem.session_id == session_id,
            ReviewItem.risk_level == "HIGH",
        ).count()

        # 查询下一条待处理条款（按页码和段落索引排序）
        next_item = db.query(ReviewItem).filter(
            ReviewItem.session_id == session_id,
            ReviewItem.risk_level == "HIGH",
            ReviewItem.human_decision == "pending",
        ).order_by(ReviewItem.page_number, ReviewItem.paragraph_index).first()

        # 从 AuditLog 获取最后操作时间
        last_decision_log = db.query(AuditLog).filter(
            AuditLog.session_id == session_id,
            AuditLog.event_type.in_(["item_approved", "item_edited", "item_rejected"]),
        ).order_by(AuditLog.occurred_at.desc()).first()

        # 尝试从 Checkpointer 获取工作流断点时间（可选增强）
        interrupted_at = None
        try:
            from app.workflow.graph import get_workflow_state
            workflow_state = get_workflow_state(session.langgraph_thread_id)
            # LangGraph StateSnapshot 的 created_at 字段记录 checkpoint 时间
            interrupted_at = getattr(workflow_state, "created_at", None)
        except Exception:
            pass

        # 回退到最后操作日志时间，再回退到 session 更新时间
        if interrupted_at is None:
            if last_decision_log is not None:
                interrupted_at = last_decision_log.occurred_at
            else:
                interrupted_at = session.updated_at

        # 写入 session_resumed 审计日志
        resume_log = AuditLog(
            session_id=session_id,
            event_type="session_resumed",
            actor_id="system",
            actor_type="system",
            metadata_json=json.dumps({
                "completed_count": decided_count,
                "total_high_risk": total_high_risk,
                "recovery_at": datetime.utcnow().isoformat(),
            }),
        )
        db.add(resume_log)
        db.commit()

        return {
            "session_id": session_id,
            "interrupted_at": (
                interrupted_at.isoformat()
                if hasattr(interrupted_at, "isoformat")
                else str(interrupted_at)
            ),
            "completed_count": decided_count,
            "total_high_risk_count": total_high_risk,
            "next_pending_item_id": next_item.id if next_item else None,
            "recovery_status": "active",
        }

    def trigger_workflow_for_session(
        self,
        session_id: str,
        thread_id: str,
        full_text: str,
        db: Session,
        precomputed_review_items: Optional[list[dict]] = None,
    ):
        """
        OCR 完成后，在后台线程启动 LangGraph 工作流。

        调用时机：ocr_service 完成字段提取后调用
        """
        # 更新 session 状态为 scanning
        session = db.query(ReviewSession).filter(
            ReviewSession.id == session_id
        ).first()
        if session:
            session.state = "scanning"
            session.updated_at = datetime.utcnow()
            db.commit()

        # 推送 state_changed 事件
        self._push_sse_event(session_id, "state_changed", {
            "state": "scanning",
            "session_id": session_id,
        })

        # 在后台线程运行工作流（传 contract_id = session_id，与 graph.py 约定一致）
        t = threading.Thread(
            target=self._run_workflow_thread,
            args=(session_id, session_id, thread_id, full_text, precomputed_review_items or []),
            daemon=True,
        )
        t.start()

    def _run_workflow_thread(
        self,
        session_id: str,
        contract_id: str,
        thread_id: str,
        full_text: str,
        precomputed_review_items: list[dict],
    ):
        """后台线程执行工作流（使用独立的 DB session，不与 FastAPI 共享）"""
        db = SessionLocal()
        try:
            from app.workflow.graph import run_workflow_sync

            # 运行工作流（在 interrupt 处暂停，返回当前状态快照）
            result = run_workflow_sync(
                session_id=session_id,
                contract_id=contract_id,
                full_text=full_text,
                thread_id=thread_id,
                precomputed_review_items=precomputed_review_items,
            )

            # 将 review_items 从 workflow state 写入数据库
            review_items_data = result.get("review_items", [])
            self._persist_review_items(session_id, review_items_data, db)

            # 根据路由结果更新 session 状态并推送相应 SSE 事件
            route_result = result.get("route_result", "auto_pass")
            high_count = result.get("high_risk_count", 0)
            medium_count = result.get("medium_risk_count", 0)

            session = db.query(ReviewSession).filter(
                ReviewSession.id == session_id
            ).first()

            if route_result == "interrupt":
                if session:
                    session.state = "hitl_pending"
                    session.hitl_subtype = "interrupt"
                    session.total_high_risk = high_count
                    session.total_medium_risk = medium_count
                    db.commit()

                pending_ids = [
                    item["id"]
                    for item in review_items_data
                    if item.get("risk_level") == "HIGH"
                ]
                self._push_sse_event(session_id, "route_interrupted", {
                    "session_id": session_id,
                    "high_risk_count": high_count,
                    "pending_item_ids": pending_ids,
                })

            elif route_result == "batch_review":
                if session:
                    session.state = "hitl_pending"
                    session.hitl_subtype = "batch_review"
                    session.total_medium_risk = medium_count
                    db.commit()

                self._push_sse_event(session_id, "route_batch_review", {
                    "session_id": session_id,
                    "medium_count": medium_count,
                })

            else:  # auto_pass
                if session:
                    session.state = "completed"
                    db.commit()

                self._push_sse_event(session_id, "route_auto_passed", {
                    "session_id": session_id,
                })

                # 无需人工介入，直接生成报告
                from app.services.report_service import generate_report_sync
                generate_report_sync(session_id, db)

        except Exception as e:
            # 记录工作流级别错误，不传播异常（后台线程中传播无意义）
            try:
                session = db.query(ReviewSession).filter(
                    ReviewSession.id == session_id
                ).first()
                if session and session.state not in ("report_ready", "aborted"):
                    log = AuditLog(
                        session_id=session_id,
                        event_type="system_failure",
                        actor_id="system",
                        actor_type="system",
                        metadata_json=json.dumps({
                            "error": str(e),
                            "node_name": "_run_workflow_thread",
                        }),
                    )
                    db.add(log)
                    db.commit()

                    self._push_sse_event(session_id, "system_failure", {
                        "error_code": "WORKFLOW_ERROR",
                        "node_name": "scanning",
                    })
            except Exception:
                pass  # 错误处理本身不应再抛出异常
        finally:
            db.close()

    def _persist_review_items(
        self, session_id: str, items_data: list, db: Session
    ):
        """将 workflow 产出的 review_items 写入数据库。"""
        # 清除该 session 已有的 review items（防止重复写入）
        db.query(ReviewItem).filter(
            ReviewItem.session_id == session_id
        ).delete()

        for item_data in items_data:
            item = ReviewItem(
                id=item_data.get("id"),
                session_id=session_id,
                clause_text=item_data.get("clause_text", ""),
                page_number=item_data.get("page_number", 1),
                paragraph_index=item_data.get("paragraph_index", 0),
                highlight_anchor=item_data.get("highlight_anchor", ""),
                char_offset_start=item_data.get("char_offset_start", 0),
                char_offset_end=item_data.get("char_offset_end", 0),
                risk_level=item_data.get("risk_level", "LOW"),
                confidence_score=item_data.get("confidence_score", 50),
                source_type=item_data.get("source_type", "ai_inference"),
                risk_category=item_data.get("risk_category", ""),
                ai_finding=item_data.get("ai_finding", ""),
                ai_reasoning=item_data.get("ai_reasoning", ""),
                suggested_revision=item_data.get("suggested_revision"),
                human_decision="pending",
            )
            db.add(item)

        # 更新 session 进度统计
        session = db.query(ReviewSession).filter(
            ReviewSession.id == session_id
        ).first()
        if session:
            session.total_high_risk = sum(
                1 for i in items_data if i.get("risk_level") == "HIGH"
            )
            session.total_medium_risk = sum(
                1 for i in items_data if i.get("risk_level") == "MEDIUM"
            )
            session.total_low_risk = sum(
                1 for i in items_data if i.get("risk_level") == "LOW"
            )

        db.commit()

        # 推送扫描进度事件
        self._push_sse_event(session_id, "scan_progress", {
            "found_count": len(items_data),
            "high_count": sum(
                1 for i in items_data if i.get("risk_level") == "HIGH"
            ),
        })

    def _push_sse_event(self, session_id: str, event_type: str, data: dict):
        """
        推送 SSE 事件（从同步后台线程安全调用）。

        使用 run_coroutine_threadsafe 将协程提交到 FastAPI 主事件循环，
        确保 asyncio.Queue 操作在正确的循环中执行，SSE subscribers 可以收到事件。
        """
        try:
            from app.core.sse import sse_manager
            from app.core import main_loop
            import asyncio

            coro = sse_manager.publish(session_id, event_type, data)

            if main_loop.loop is not None and main_loop.loop.is_running():
                # 提交到 FastAPI 主事件循环（跨线程安全）
                future = asyncio.run_coroutine_threadsafe(coro, main_loop.loop)
                future.result(timeout=5)  # 等待最多 5 秒
            else:
                # 回退：在当前线程直接运行（适用于同步上下文）
                asyncio.run(coro)
        except Exception:
            pass  # SSE 推送失败不影响主业务流程


# 全局单例，供 T3 API 层直接导入使用
hitl_service = HITLService()
