"""
聊天相关的 Pydantic 模型
"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SSEEventType(str, Enum):
    """SSE 事件类型"""
    THINKING = "thinking"  # AI 思考过程
    TEXT = "text"          # 文本内容
    SQL = "sql"            # 生成的 SQL
    DATA = "data"          # 查询结果数据
    CHART = "chart"        # 图表配置
    ERROR = "error"        # 错误信息
    DONE = "done"          # 完成标记


class ChatRequest(BaseModel):
    """聊天请求"""
    session_id: str = Field(..., description="会话 ID")
    message: str = Field(..., min_length=1, description="用户消息")


class ChatMessage(BaseModel):
    """聊天消息"""
    id: Optional[int] = None
    session_id: str
    role: MessageRole
    content: str
    sql_query: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class SSEEvent(BaseModel):
    """SSE 事件"""
    event: SSEEventType
    data: Any
    
    def to_sse(self) -> str:
        """转换为 SSE 格式字符串
        
        注意：SSE 规范要求多行数据的每行都要以 'data: ' 开头
        """
        import json
        if isinstance(self.data, str):
            data_str = self.data
        else:
            data_str = json.dumps(self.data, ensure_ascii=False)
        
        # 处理多行数据：每行都需要 'data: ' 前缀
        lines = data_str.split('\n')
        if len(lines) > 1:
            data_part = '\n'.join(f"data: {line}" for line in lines)
        else:
            data_part = f"data: {data_str}"
        
        return f"event: {self.event.value}\n{data_part}\n\n"


class ChartType(str, Enum):
    """图表类型"""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    TABLE = "table"


class ChartConfig(BaseModel):
    """图表配置"""
    type: ChartType = Field(default=ChartType.BAR, description="图表类型")
    title: str = Field(default="", description="图表标题")
    data: list[dict[str, Any]] = Field(default_factory=list, description="图表数据")
    x_field: Optional[str] = Field(None, alias="xField", description="X 轴字段")
    y_field: Optional[str] = Field(None, alias="yField", description="Y 轴字段")
    series_field: Optional[str] = Field(None, alias="seriesField", description="系列字段")
    
    class Config:
        populate_by_name = True


class QueryResult(BaseModel):
    """查询结果"""
    sql: str = Field(..., description="执行的 SQL")
    columns: list[str] = Field(default_factory=list, description="列名")
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    row_count: int = Field(default=0, description="行数")


class DatabaseSchema(BaseModel):
    """数据库结构"""
    dialect: str
    tables: list[dict[str, Any]]
