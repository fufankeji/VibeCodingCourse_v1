import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator

from ..database import get_db
from ..schemas import ChatRequest
from ..models import Conversation, Message
from ..services.deepseek_service import deepseek_service

router = APIRouter(prefix="/api", tags=["chat"])


async def generate_sse_stream(
    request: ChatRequest,
    db: AsyncSession
) -> AsyncGenerator[str, None]:
    """生成 SSE 流式响应"""
    
    conversation_id = request.conversation_id
    
    # 如果有 conversation_id，获取历史消息
    if conversation_id:
        conversation = await db.get(Conversation, conversation_id)
        if conversation:
            # 更新 thinking_enabled 状态
            conversation.thinking_enabled = "true" if request.thinking_enabled else "false"
            await db.commit()
    
    # 准备发送给 DeepSeek 的消息
    api_messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    full_reasoning = ""
    full_content = ""
    
    # 流式调用 DeepSeek API
    async for chunk in deepseek_service.stream_chat(
        messages=api_messages,
        thinking_enabled=request.thinking_enabled
    ):
        if chunk["type"] == "reasoning":
            full_reasoning += chunk["data"]
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        
        elif chunk["type"] == "content":
            full_content += chunk["data"]
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        
        elif chunk["type"] == "done":
            # 保存用户消息和助手消息到数据库
            if conversation_id:
                # 保存用户消息（最后一条）
                last_user_msg = request.messages[-1]
                user_message = Message(
                    conversation_id=conversation_id,
                    role="user",
                    content=last_user_msg.content
                )
                db.add(user_message)
                
                # 保存助手消息
                assistant_message = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_content,
                    reasoning_content=full_reasoning if full_reasoning else None
                )
                db.add(assistant_message)
                
                # 更新对话标题（如果是第一条消息）
                conversation = await db.get(Conversation, conversation_id)
                if conversation and conversation.title == "New Chat":
                    # 使用用户第一条消息生成标题
                    title = last_user_msg.content[:30]
                    if len(last_user_msg.content) > 30:
                        title += "..."
                    conversation.title = title
                
                await db.commit()
            
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        
        elif chunk["type"] == "error":
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    聊天接口 - SSE 流式响应
    
    Request Body:
        - messages: 消息列表
        - conversation_id: 对话 ID（可选）
        - thinking_enabled: 是否开启思考模式
    
    Response:
        SSE 流式响应，格式：
        - data: {"type": "reasoning", "data": "思考内容"}
        - data: {"type": "content", "data": "回答内容"}
        - data: {"type": "done", "reasoning": "完整思考", "content": "完整回答"}
        - data: {"type": "error", "error": "错误信息"}
    """
    return StreamingResponse(
        generate_sse_stream(request, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
