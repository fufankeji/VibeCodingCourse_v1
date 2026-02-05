"""
会话持久化存储模块
"""
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from app.db.connection import get_raw_connection, ensure_data_dir


class SessionStore:
    """会话存储管理器"""
    
    def __init__(self):
        ensure_data_dir()
        self._init_tables()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = get_raw_connection()
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_tables(self):
        """初始化表结构"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sql_query TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
        conn.close()
    
    def create_session(self, title: Optional[str] = None) -> dict:
        """
        创建新会话
        
        Args:
            title: 会话标题，为空则自动生成
        
        Returns:
            会话信息字典
        """
        session_id = str(uuid.uuid4())
        now = datetime.now()
        
        if not title:
            title = f"新会话 {now.strftime('%m-%d %H:%M')}"
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now)
        )
        
        conn.commit()
        conn.close()
        
        return {
            "id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "message_count": 0
        }
    
    def get_session(self, session_id: str) -> Optional[dict]:
        """
        获取会话信息
        
        Args:
            session_id: 会话 ID
        
        Returns:
            会话信息字典，不存在返回 None
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT s.*, COUNT(m.id) as message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON s.id = m.session_id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (session_id,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """
        获取会话列表
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
        
        Returns:
            会话列表
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT s.*, COUNT(m.id) as message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_session(self, session_id: str, title: str) -> bool:
        """
        更新会话标题
        
        Args:
            session_id: 会话 ID
            title: 新标题
        
        Returns:
            是否更新成功
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now(), session_id)
        )
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def delete_session(self, session_id: str) -> bool:
        """
        删除会话及其所有消息
        
        Args:
            session_id: 会话 ID
        
        Returns:
            是否删除成功
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 先删除消息
        cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        # 再删除会话
        cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def touch_session(self, session_id: str):
        """更新会话的最后更新时间"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (datetime.now(), session_id)
        )
        
        conn.commit()
        conn.close()
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sql_query: Optional[str] = None
    ) -> dict:
        """
        添加消息
        
        Args:
            session_id: 会话 ID
            role: 角色 (user/assistant/system)
            content: 消息内容
            sql_query: SQL 查询（可选）
        
        Returns:
            消息信息字典
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now()
        
        cursor.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, sql_query, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, sql_query, now)
        )
        
        message_id = cursor.lastrowid
        
        # 更新会话时间
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id)
        )
        
        conn.commit()
        conn.close()
        
        return {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "sql_query": sql_query,
            "created_at": now
        }
    
    def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        """
        获取会话消息
        
        Args:
            session_id: 会话 ID
            limit: 返回数量限制
        
        Returns:
            消息列表
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT * FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> list[dict]:
        """
        获取最近的消息（用于上下文记忆）
        
        Args:
            session_id: 会话 ID
            limit: 返回数量限制
        
        Returns:
            消息列表（按时间正序）
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT * FROM (
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) sub
            ORDER BY created_at ASC
            """,
            (session_id, limit)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# 全局会话存储实例
session_store = SessionStore()
