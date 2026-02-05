"""
聊天 API 路由 - SSE 流式响应
"""
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.agent import run_sql_agent
from app.db.session_store import session_store
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


async def event_generator(session_id: str, message: str):
    """
    SSE 事件生成器
    
    Args:
        session_id: 会话 ID
        message: 用户消息
    
    Yields:
        SSE 格式的事件字符串
    """
    async for event in run_sql_agent(session_id, message):
        yield event.to_sse()


@router.post("")
async def chat(request: ChatRequest):
    """
    聊天接口 - 流式返回 AI 响应
    
    Args:
        request: 聊天请求（session_id, message）
    
    Returns:
        SSE 流式响应
    
    事件类型：
    - thinking: AI 思考过程
    - text: 文本内容
    - sql: 生成的 SQL
    - data: 查询结果数据
    - chart: 图表配置
    - error: 错误信息
    - done: 完成标记
    """
    # 验证会话是否存在
    session = session_store.get_session(request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {request.session_id} not found"
        )
    
    return StreamingResponse(
        event_generator(request.session_id, request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
        }
    )


@router.get("/test")
async def test_chat():
    """
    测试聊天接口（用于验证 SSE 连接）
    """
    async def test_generator():
        import asyncio
        
        yield "event: text\ndata: 这是一条测试消息\n\n"
        await asyncio.sleep(0.5)
        yield "event: text\ndata: SSE 连接正常工作\n\n"
        await asyncio.sleep(0.5)
        yield "event: done\ndata: {}\n\n"
    
    return StreamingResponse(
        test_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
