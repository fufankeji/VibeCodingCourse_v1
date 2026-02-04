from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MessageBase(BaseModel):
    role: str
    content: str


class MessageCreate(MessageBase):
    pass


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    reasoning_content: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"
    thinking_enabled: Optional[bool] = False


class ConversationResponse(BaseModel):
    id: str
    title: str
    model: str
    thinking_enabled: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationWithMessages(ConversationResponse):
    messages: List[MessageResponse] = []


class ChatRequest(BaseModel):
    messages: List[MessageBase]
    conversation_id: Optional[str] = None
    thinking_enabled: Optional[bool] = False


class StreamChunk(BaseModel):
    type: str  # "reasoning" | "content" | "done" | "error"
    data: Optional[str] = None
    error: Optional[str] = None
