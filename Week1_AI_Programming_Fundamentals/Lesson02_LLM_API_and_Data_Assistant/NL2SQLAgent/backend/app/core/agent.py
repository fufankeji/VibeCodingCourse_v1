"""
SQL Agent 模块
"""
import json
import re
from typing import AsyncGenerator, Optional

from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage, BaseMessage

from app.core.llm import get_llm, SQL_AGENT_SYSTEM_PROMPT
from app.core.memory import memory_manager
from app.db.connection import get_sql_database
from app.schemas.chat import SSEEvent, SSEEventType, ChartConfig, ChartType


class SQLAgent:
    """
    SQL Agent - 处理自然语言到 SQL 的转换和执行
    """
    
    def __init__(self, session_id: str, max_iterations: int = 6):
        """
        初始化 SQL Agent
        
        Args:
            session_id: 会话 ID
            max_iterations: 最大迭代次数
        """
        self.session_id = session_id
        self.max_iterations = max_iterations
        
        # 初始化组件
        self.db = get_sql_database()
        self.llm = get_llm(streaming=True)
        
        # 创建工具集
        self.toolkit = SQLDatabaseToolkit(db=self.db, llm=self.llm)
        self.tools = self.toolkit.get_tools()
        self.tool_dict = {tool.name: tool for tool in self.tools}
        
        # 绑定工具到 LLM
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        
        # 系统提示
        self.system_prompt = SQL_AGENT_SYSTEM_PROMPT.format(
            dialect=self.db.dialect,
            top_k=10
        )
    
    async def run(self, user_input: str) -> AsyncGenerator[SSEEvent, None]:
        """
        运行 Agent 处理用户输入
        
        Args:
            user_input: 用户输入
        
        Yields:
            SSE 事件
        """
        # 获取历史消息
        history = memory_manager.get_messages(self.session_id)
        
        # 构建消息列表
        messages: list[BaseMessage] = [
            SystemMessage(content=self.system_prompt),
            *history,
            HumanMessage(content=user_input)
        ]
        
        # 保存用户消息
        memory_manager.add_user_message(self.session_id, user_input)
        
        # 收集完整响应
        full_response = ""
        executed_sql = None
        query_result = None
        
        try:
            for iteration in range(self.max_iterations):
                # 调用 LLM
                response = await self._call_llm(messages)
                
                # 处理文本内容
                if response.content:
                    full_response += response.content
                    yield SSEEvent(event=SSEEventType.TEXT, data=response.content)
                
                messages.append(response)
                
                # 检查是否有工具调用
                if not response.tool_calls:
                    # 没有工具调用，Agent 完成
                    break
                
                # 执行工具调用
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]
                    
                    # 发送思考过程
                    yield SSEEvent(
                        event=SSEEventType.THINKING,
                        data=f"正在执行: {tool_name}"
                    )
                    
                    # 执行工具
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    
                    # 如果是 SQL 查询，发送 SQL 事件
                    if tool_name == "sql_db_query":
                        query = tool_args.get("query", "")
                        executed_sql = query
                        query_result = tool_result
                        
                        yield SSEEvent(event=SSEEventType.SQL, data=query)
                        
                        # 解析并发送数据
                        parsed_data = self._parse_query_result(tool_result, query)
                        if parsed_data:
                            yield SSEEvent(event=SSEEventType.DATA, data=parsed_data)
                            
                            # 生成图表配置
                            chart_config = self._generate_chart_config(query, parsed_data)
                            if chart_config:
                                yield SSEEvent(event=SSEEventType.CHART, data=chart_config)
                    
                    # 添加工具结果消息
                    messages.append(ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_id
                    ))
            
            # 保存助手响应
            memory_manager.add_assistant_message(
                self.session_id, 
                full_response,
                executed_sql
            )
            
        except Exception as e:
            yield SSEEvent(event=SSEEventType.ERROR, data=str(e))
        
        finally:
            yield SSEEvent(event=SSEEventType.DONE, data={})
    
    async def _call_llm(self, messages: list[BaseMessage]) -> AIMessage:
        """调用 LLM（非流式，获取完整响应）"""
        # 使用非流式调用获取完整响应（包括 tool_calls）
        llm_non_streaming = get_llm(streaming=False)
        llm_with_tools = llm_non_streaming.bind_tools(self.tools)
        
        response = await llm_with_tools.ainvoke(messages)
        return response
    
    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行工具调用"""
        if tool_name not in self.tool_dict:
            return f"Error: Unknown tool {tool_name}"
        
        tool = self.tool_dict[tool_name]
        
        try:
            # 根据工具类型获取正确的参数
            if tool_name == "sql_db_list_tables":
                tool_input = ""
            elif tool_name == "sql_db_schema":
                tool_input = tool_args.get("table_names", "")
            elif tool_name == "sql_db_query":
                tool_input = tool_args.get("query", "")
            elif tool_name == "sql_db_query_checker":
                tool_input = tool_args.get("query", "")
            else:
                tool_input = str(tool_args)
            
            result = tool.invoke(tool_input)
            return str(result)
            
        except Exception as e:
            return f"Error executing {tool_name}: {e}"
    
    def _parse_query_result(self, result: str, sql: str = "") -> Optional[dict]:
        """
        解析查询结果
        
        Args:
            result: SQL 查询返回的字符串结果
            sql: 原始 SQL 语句（用于提取列名）
        
        Returns:
            包含 columns, rows, raw 的数据字典
        """
        try:
            # 尝试解析元组列表格式: [(a, b), (c, d)]
            if result.startswith("[") and result.endswith("]"):
                # 使用 eval 解析（注意：生产环境应使用更安全的方式）
                data = eval(result)
                
                if isinstance(data, list) and len(data) > 0:
                    # 转换为字典列表
                    if isinstance(data[0], tuple):
                        # 从 SQL 提取列名
                        columns = self._extract_columns_from_sql(sql, len(data[0]))
                        
                        # 构建 rows 数据
                        rows = []
                        for item in data:
                            if len(item) >= 2:
                                rows.append({
                                    "name": str(item[0]),
                                    "value": item[1] if len(item) == 2 else list(item[1:])
                                })
                        
                        return {
                            "columns": columns,
                            "rows": rows,
                            "raw": data
                        }
            
            return None
            
        except Exception:
            return None
    
    def _extract_columns_from_sql(self, sql: str, num_columns: int) -> list:
        """
        从 SQL SELECT 语句中提取列名
        
        Args:
            sql: SQL 语句
            num_columns: 数据中的列数
        
        Returns:
            列名列表
        """
        try:
            # 提取 SELECT ... FROM 之间的部分
            match = re.search(r'SELECT\s+(.+?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if match:
                select_clause = match.group(1).strip()
                
                # 处理 SELECT * 的情况
                if select_clause == '*':
                    return [f"column_{i+1}" for i in range(num_columns)]
                
                # 分割列定义（注意处理函数中的逗号）
                columns = []
                depth = 0
                current = ""
                
                for char in select_clause:
                    if char == '(':
                        depth += 1
                        current += char
                    elif char == ')':
                        depth -= 1
                        current += char
                    elif char == ',' and depth == 0:
                        columns.append(current.strip())
                        current = ""
                    else:
                        current += char
                
                if current.strip():
                    columns.append(current.strip())
                
                # 提取最终列名（考虑 AS 别名）
                final_columns = []
                for col in columns:
                    # 检查 AS 别名
                    as_match = re.search(r'\s+AS\s+(\w+)\s*$', col, re.IGNORECASE)
                    if as_match:
                        final_columns.append(as_match.group(1))
                    else:
                        # 提取最后的标识符
                        # 处理 SUM(amount), COUNT(*), table.column 等
                        simple_match = re.search(r'(\w+)\s*$', col)
                        if simple_match:
                            final_columns.append(simple_match.group(1))
                        else:
                            final_columns.append(col)
                
                return final_columns if len(final_columns) == num_columns else [f"column_{i+1}" for i in range(num_columns)]
            
            return [f"column_{i+1}" for i in range(num_columns)]
            
        except Exception:
            return [f"column_{i+1}" for i in range(num_columns)]
    
    def _generate_chart_config(self, sql: str, data: dict) -> Optional[dict]:
        """根据 SQL 和数据生成图表配置"""
        try:
            rows = data.get("rows", [])
            if not rows:
                return None
            
            # 分析 SQL 确定图表类型
            sql_lower = sql.lower()
            
            # 包含 GROUP BY 的聚合查询适合柱状图或饼图
            if "group by" in sql_lower:
                # 如果数据量小于等于 6，使用饼图
                if len(rows) <= 6:
                    chart_type = "pie"
                else:
                    chart_type = "bar"
            elif "order by" in sql_lower and "limit" in sql_lower:
                # 排序后的 TOP N 查询适合柱状图
                chart_type = "bar"
            else:
                # 默认使用柱状图
                chart_type = "bar"
            
            # 构建图表配置
            chart_data = []
            for row in rows:
                chart_data.append({
                    "name": row.get("name", ""),
                    "value": row.get("value", 0)
                })
            
            # 生成标题
            title = self._extract_chart_title(sql)
            
            return {
                "type": chart_type,
                "title": title,
                "data": chart_data,
                "xField": "name",
                "yField": "value"
            }
            
        except Exception:
            return None
    
    def _extract_chart_title(self, sql: str) -> str:
        """从 SQL 提取图表标题"""
        sql_lower = sql.lower()
        
        # 尝试提取聚合函数和字段
        if "sum(" in sql_lower:
            return "汇总统计"
        elif "count(" in sql_lower:
            return "数量统计"
        elif "avg(" in sql_lower:
            return "平均值统计"
        elif "max(" in sql_lower:
            return "最大值统计"
        elif "min(" in sql_lower:
            return "最小值统计"
        
        return "查询结果"


async def run_sql_agent(session_id: str, user_input: str) -> AsyncGenerator[SSEEvent, None]:
    """
    运行 SQL Agent 的便捷函数
    
    Args:
        session_id: 会话 ID
        user_input: 用户输入
    
    Yields:
        SSE 事件
    """
    agent = SQLAgent(session_id)
    async for event in agent.run(user_input):
        yield event
