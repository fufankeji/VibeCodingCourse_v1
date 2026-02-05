"""
会话相关的 Pydantic 模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, description="会话标题，为空则自动生成")


class SessionUpdate(BaseModel):
    """更新会话请求"""
    title: str = Field(..., min_length=1, description="会话标题")


class Session(BaseModel):
    """会话信息"""
    id: str = Field(..., description="会话 ID")
    title: str = Field(..., description="会话标题")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    message_count: int = Field(default=0, description="消息数量")
    
    class Config:
        from_attributes = True


class SessionWithMessages(Session):
    """带消息的会话信息"""
    messages: list = Field(default_factory=list, description="消息列表")
