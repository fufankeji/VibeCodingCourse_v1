"""
会话管理 API 路由
"""
from fastapi import APIRouter, HTTPException, status

from app.db.session_store import session_store
from app.schemas.session import Session, SessionCreate, SessionUpdate, SessionWithMessages

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[Session])
async def list_sessions(limit: int = 50, offset: int = 0):
    """
    获取会话列表
    
    Args:
        limit: 返回数量限制（默认 50）
        offset: 偏移量
    
    Returns:
        会话列表
    """
    sessions = session_store.list_sessions(limit=limit, offset=offset)
    return sessions


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(request: SessionCreate = None):
    """
    创建新会话
    
    Args:
        request: 创建请求（可选标题）
    
    Returns:
        新创建的会话
    """
    title = request.title if request else None
    session = session_store.create_session(title=title)
    return session


@router.get("/{session_id}", response_model=SessionWithMessages)
async def get_session(session_id: str):
    """
    获取会话详情（包含消息）
    
    Args:
        session_id: 会话 ID
    
    Returns:
        会话详情
    """
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # 获取消息
    messages = session_store.get_messages(session_id)
    session["messages"] = messages
    
    return session


@router.put("/{session_id}", response_model=Session)
async def update_session(session_id: str, request: SessionUpdate):
    """
    更新会话标题
    
    Args:
        session_id: 会话 ID
        request: 更新请求
    
    Returns:
        更新后的会话
    """
    success = session_store.update_session(session_id, request.title)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    session = session_store.get_session(session_id)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str):
    """
    删除会话
    
    Args:
        session_id: 会话 ID
    
    Returns:
        无内容 (204 No Content)
    """
    success = session_store.delete_session(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    return None


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 100):
    """
    获取会话消息列表
    
    Args:
        session_id: 会话 ID
        limit: 返回数量限制
    
    Returns:
        消息列表
    """
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    messages = session_store.get_messages(session_id, limit=limit)
    return messages
