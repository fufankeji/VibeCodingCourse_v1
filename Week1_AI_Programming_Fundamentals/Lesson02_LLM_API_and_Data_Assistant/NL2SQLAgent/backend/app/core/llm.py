"""
LLM 接入模块 - 阿里云百炼 Qwen3 配置
"""
import os
from functools import lru_cache
from typing import Optional

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.language_models import BaseChatModel

from app.config import get_settings


@lru_cache
def get_llm(
    model: Optional[str] = None,
    streaming: bool = True,
    temperature: float = 0.7,
) -> BaseChatModel:
    """
    获取 LLM 实例
    
    Args:
        model: 模型名称，默认使用配置中的模型
        streaming: 是否启用流式输出
        temperature: 温度参数
    
    Returns:
        ChatTongyi 实例
    """
    settings = get_settings()
    
    # 确保 API Key 已设置
    api_key = settings.dashscope_api_key
    if not api_key or api_key == "your_api_key_here":
        raise ValueError("DASHSCOPE_API_KEY not configured. Please set it in .env file.")
    
    # 设置环境变量（ChatTongyi 需要）
    os.environ["DASHSCOPE_API_KEY"] = api_key
    
    return ChatTongyi(
        model=model or "qwen3-max",
        streaming=streaming,
        temperature=temperature,
    )


def get_llm_with_tools(tools: list, model: Optional[str] = None) -> BaseChatModel:
    """
    获取绑定工具的 LLM 实例
    
    Args:
        tools: 工具列表
        model: 模型名称
    
    Returns:
        绑定工具后的 LLM 实例
    """
    llm = get_llm(model=model, streaming=True)
    return llm.bind_tools(tools)


# 预定义的系统提示模板
SQL_AGENT_SYSTEM_PROMPT = """你是一个专业的 SQL 数据库分析助手。

你的任务是帮助用户通过自然语言查询数据库。请按以下步骤操作：

1. **理解问题**：仔细分析用户的查询意图
2. **查看表结构**：使用 sql_db_list_tables 和 sql_db_schema 了解数据库结构
3. **编写 SQL**：根据表结构编写正确的 SQL 查询
4. **验证 SQL**：使用 sql_db_query_checker 检查 SQL 语法
5. **执行查询**：使用 sql_db_query 执行查询
6. **分析结果**：解读查询结果并给出清晰的回答

数据库方言: {dialect}

**注意事项：**
- 只执行 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP 等操作
- 查询结果限制在 {top_k} 条以内，除非用户明确要求更多
- 优先选择相关列，避免 SELECT *
- 如果查询出错，分析错误原因并重新编写 SQL

请用中文回答用户问题，并在回答中说明你的分析思路。
"""
