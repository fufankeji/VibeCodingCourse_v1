from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import List

from ..database import get_db
from ..schemas import ConversationCreate, ConversationResponse, ConversationWithMessages, MessageResponse
from ..models import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """获取所有对话列表"""
    result = await db.execute(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return conversations


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建新对话"""
    conversation = Conversation(
        title=data.title or "New Chat",
        thinking_enabled="true" if data.thinking_enabled else "false"
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取对话详情及消息"""
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # 按时间排序消息
    conversation.messages.sort(key=lambda m: m.created_at)
    
    return conversation


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除对话"""
    conversation = await db.get(Conversation, conversation_id)
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    await db.delete(conversation)
    await db.commit()
    
    return {"message": "Conversation deleted successfully"}


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db)
):
    """更新对话"""
    conversation = await db.get(Conversation, conversation_id)
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if data.title:
        conversation.title = data.title
    if data.thinking_enabled is not None:
        conversation.thinking_enabled = "true" if data.thinking_enabled else "false"
    
    await db.commit()
    await db.refresh(conversation)
    
    return conversation
