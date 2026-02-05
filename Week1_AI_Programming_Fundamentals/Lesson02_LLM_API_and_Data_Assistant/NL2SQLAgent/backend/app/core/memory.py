"""
上下文记忆管理模块
"""
from typing import Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage

from app.db.session_store import session_store


class SessionMemoryManager:
    """
    基于会话 ID 的记忆管理器
    
    从数据库加载历史消息，转换为 LangChain 消息格式
    """
    
    def __init__(self, window_size: int = 10):
        """
        初始化记忆管理器
        
        Args:
            window_size: 保留的最近消息轮数（一问一答为一轮）
        """
        self.window_size = window_size
        self._cache: dict[str, list[BaseMessage]] = {}
    
    def get_messages(self, session_id: str) -> list[BaseMessage]:
        """
        获取会话的历史消息
        
        Args:
            session_id: 会话 ID
        
        Returns:
            LangChain 消息列表
        """
        # 从缓存获取
        if session_id in self._cache:
            return self._cache[session_id]
        
        # 从数据库加载
        messages = self._load_from_db(session_id)
        self._cache[session_id] = messages
        
        return messages
    
    def _load_from_db(self, session_id: str) -> list[BaseMessage]:
        """从数据库加载历史消息"""
        # 获取最近的消息（window_size * 2 条，因为一问一答）
        db_messages = session_store.get_recent_messages(
            session_id, 
            limit=self.window_size * 2
        )
        
        messages = []
        for msg in db_messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
        
        return messages
    
    def add_user_message(self, session_id: str, content: str):
        """
        添加用户消息
        
        Args:
            session_id: 会话 ID
            content: 消息内容
        """
        # 保存到数据库
        session_store.add_message(session_id, "user", content)
        
        # 更新缓存
        if session_id not in self._cache:
            self._cache[session_id] = self._load_from_db(session_id)
        else:
            self._cache[session_id].append(HumanMessage(content=content))
            # 保持窗口大小
            self._trim_cache(session_id)
    
    def add_assistant_message(
        self, 
        session_id: str, 
        content: str,
        sql_query: Optional[str] = None
    ):
        """
        添加助手消息
        
        Args:
            session_id: 会话 ID
            content: 消息内容
            sql_query: SQL 查询（可选）
        """
        # 保存到数据库
        session_store.add_message(session_id, "assistant", content, sql_query)
        
        # 更新缓存
        if session_id not in self._cache:
            self._cache[session_id] = self._load_from_db(session_id)
        else:
            self._cache[session_id].append(AIMessage(content=content))
            # 保持窗口大小
            self._trim_cache(session_id)
    
    def _trim_cache(self, session_id: str):
        """修剪缓存，保持窗口大小"""
        if session_id in self._cache:
            max_messages = self.window_size * 2
            if len(self._cache[session_id]) > max_messages:
                self._cache[session_id] = self._cache[session_id][-max_messages:]
    
    def clear_memory(self, session_id: str):
        """
        清除会话记忆（仅清除缓存，不删除数据库记录）
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._cache:
            del self._cache[session_id]
    
    def refresh_memory(self, session_id: str):
        """
        刷新会话记忆（从数据库重新加载）
        
        Args:
            session_id: 会话 ID
        """
        self._cache[session_id] = self._load_from_db(session_id)


# 全局记忆管理器实例
memory_manager = SessionMemoryManager(window_size=10)
