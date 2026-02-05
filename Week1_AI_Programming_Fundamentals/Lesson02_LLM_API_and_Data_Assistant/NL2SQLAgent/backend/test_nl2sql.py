"""
测试 NL2SQL 组件与 Qwen3 的集成
验证 SQLDatabase、SQLDatabaseToolkit、SQL Agent 的实际输入输出参数
"""
import os
import sqlite3

# 设置 API Key
os.environ["DASHSCOPE_API_KEY"] = "sk-89617ce8f26248d4b22523f3e362b0b6"

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.messages import HumanMessage, SystemMessage


def create_sample_database():
    """创建示例数据库"""
    db_path = "./data/sample.db"
    os.makedirs("./data", exist_ok=True)
    
    # 如果数据库已存在，先删除
    if os.path.exists(db_path):
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建销售表
    cursor.execute("""
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            sale_date DATE NOT NULL
        )
    """)
    
    # 插入示例数据
    sample_data = [
        (1, '笔记本电脑', '电子产品', 10, 5999.00, '2024-01-15'),
        (2, '无线鼠标', '电子产品', 50, 99.00, '2024-01-15'),
        (3, '机械键盘', '电子产品', 30, 299.00, '2024-01-16'),
        (4, '显示器', '电子产品', 15, 1299.00, '2024-01-17'),
        (5, '办公椅', '家具', 20, 599.00, '2024-01-18'),
        (6, '办公桌', '家具', 10, 899.00, '2024-01-18'),
        (7, '打印纸', '办公用品', 100, 29.00, '2024-01-19'),
        (8, '签字笔', '办公用品', 200, 5.00, '2024-01-19'),
        (9, '文件夹', '办公用品', 150, 15.00, '2024-01-20'),
        (10, '台灯', '家具', 25, 199.00, '2024-01-20'),
    ]
    
    cursor.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)",
        sample_data
    )
    
    conn.commit()
    conn.close()
    print(f"✅ 示例数据库已创建: {db_path}")
    return db_path


def test_sql_database():
    """测试 SQLDatabase 组件"""
    print("=" * 60)
    print("测试 1: SQLDatabase 组件")
    print("=" * 60)
    
    db = SQLDatabase.from_uri("sqlite:///./data/sample.db")
    
    # 1. 基本属性
    print(f"\n--- 基本属性 ---")
    print(f"dialect: {db.dialect}")
    print(f"table_info 类型: {type(db.table_info)}")
    
    # 2. 获取表列表
    print(f"\n--- get_usable_table_names() ---")
    tables = db.get_usable_table_names()
    print(f"返回类型: {type(tables)}")
    print(f"返回值: {tables}")
    
    # 3. 获取表结构
    print(f"\n--- get_table_info() ---")
    table_info = db.get_table_info()
    print(f"返回类型: {type(table_info)}")
    print(f"返回值:\n{table_info}")
    
    # 4. 执行查询
    print(f"\n--- run() 方法 ---")
    result = db.run("SELECT * FROM sales LIMIT 3")
    print(f"返回类型: {type(result)}")
    print(f"返回值: {result}")
    
    # 5. 带参数的查询
    print(f"\n--- run_no_throw() 方法 ---")
    result2 = db.run_no_throw("SELECT COUNT(*) as count FROM sales")
    print(f"返回类型: {type(result2)}")
    print(f"返回值: {result2}")
    
    return db


def test_sql_toolkit(db):
    """测试 SQLDatabaseToolkit 组件"""
    print("\n" + "=" * 60)
    print("测试 2: SQLDatabaseToolkit 组件")
    print("=" * 60)
    
    llm = ChatTongyi(model="qwen3-max")
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    
    # 获取所有工具
    tools = toolkit.get_tools()
    print(f"\n--- 工具列表 ---")
    print(f"工具数量: {len(tools)}")
    
    for i, tool in enumerate(tools):
        print(f"\n工具 {i+1}:")
        print(f"  name: {tool.name}")
        print(f"  description: {tool.description[:100]}...")
        print(f"  args_schema: {tool.args_schema.schema() if tool.args_schema else 'None'}")
    
    return tools


def test_tools_invoke(tools):
    """测试各个工具的调用"""
    print("\n" + "=" * 60)
    print("测试 3: 工具调用测试")
    print("=" * 60)
    
    # 构建工具字典
    tool_dict = {tool.name: tool for tool in tools}
    
    # 1. 测试 sql_db_list_tables
    print(f"\n--- sql_db_list_tables ---")
    if "sql_db_list_tables" in tool_dict:
        tool = tool_dict["sql_db_list_tables"]
        result = tool.invoke("")
        print(f"输入: '' (空字符串)")
        print(f"返回类型: {type(result)}")
        print(f"返回值: {result}")
    
    # 2. 测试 sql_db_schema
    print(f"\n--- sql_db_schema ---")
    if "sql_db_schema" in tool_dict:
        tool = tool_dict["sql_db_schema"]
        result = tool.invoke("sales")
        print(f"输入: 'sales'")
        print(f"返回类型: {type(result)}")
        print(f"返回值:\n{result}")
    
    # 3. 测试 sql_db_query
    print(f"\n--- sql_db_query ---")
    if "sql_db_query" in tool_dict:
        tool = tool_dict["sql_db_query"]
        result = tool.invoke("SELECT category, SUM(quantity * price) as total FROM sales GROUP BY category")
        print(f"输入: 'SELECT category, SUM(quantity * price) as total FROM sales GROUP BY category'")
        print(f"返回类型: {type(result)}")
        print(f"返回值: {result}")
    
    # 4. 测试 sql_db_query_checker
    print(f"\n--- sql_db_query_checker ---")
    if "sql_db_query_checker" in tool_dict:
        tool = tool_dict["sql_db_query_checker"]
        result = tool.invoke("SELEC * FROM sales")  # 故意写错
        print(f"输入: 'SELEC * FROM sales' (错误SQL)")
        print(f"返回类型: {type(result)}")
        print(f"返回值: {result}")


def test_llm_with_tools(tools):
    """测试 LLM 绑定工具后的调用"""
    print("\n" + "=" * 60)
    print("测试 4: LLM 绑定工具调用")
    print("=" * 60)
    
    llm = ChatTongyi(model="qwen3-max")
    llm_with_tools = llm.bind_tools(tools)
    
    # 构建系统提示
    system_prompt = """你是一个 SQL 数据库助手。
当用户询问数据相关问题时，你需要：
1. 首先使用 sql_db_list_tables 查看可用的表
2. 使用 sql_db_schema 获取相关表的结构
3. 编写 SQL 查询语句
4. 使用 sql_db_query 执行查询并返回结果

数据库方言: SQLite
"""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="请查询各类别的销售总额")
    ]
    
    print(f"\n--- 非流式调用 ---")
    response = llm_with_tools.invoke(messages)
    print(f"content: {response.content[:200] if response.content else '(空)'}...")
    print(f"tool_calls: {response.tool_calls}")
    print(f"response_metadata: {response.response_metadata}")
    
    # 如果有工具调用，执行工具
    if response.tool_calls:
        tool_dict = {tool.name: tool for tool in tools}
        for tc in response.tool_calls:
            print(f"\n--- 执行工具: {tc['name']} ---")
            print(f"参数: {tc['args']}")
            if tc['name'] in tool_dict:
                tool_result = tool_dict[tc['name']].invoke(tc['args'])
                print(f"工具返回: {tool_result[:200] if len(str(tool_result)) > 200 else tool_result}")


def test_streaming_with_tools(tools):
    """测试带工具的流式输出"""
    print("\n" + "=" * 60)
    print("测试 5: 带工具的流式输出")
    print("=" * 60)
    
    llm = ChatTongyi(model="qwen3-max", streaming=True)
    llm_with_tools = llm.bind_tools(tools)
    
    messages = [
        SystemMessage(content="你是SQL助手，使用提供的工具查询数据库。"),
        HumanMessage(content="数据库里有哪些表？")
    ]
    
    print(f"\n--- 流式响应 ---")
    collected_content = ""
    collected_tool_calls = []
    
    for chunk in llm_with_tools.stream(messages):
        print(f"\n--- Chunk ---")
        print(f"content: {repr(chunk.content)}")
        print(f"id: {chunk.id}")
        
        if chunk.content:
            collected_content += chunk.content
        
        if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
            print(f"tool_calls: {chunk.tool_calls}")
            collected_tool_calls.extend(chunk.tool_calls)
        
        if hasattr(chunk, 'tool_call_chunks') and chunk.tool_call_chunks:
            print(f"tool_call_chunks: {chunk.tool_call_chunks}")
        
        if chunk.response_metadata:
            print(f"response_metadata: {chunk.response_metadata}")
    
    print(f"\n--- 汇总结果 ---")
    print(f"完整 content: {collected_content}")
    print(f"tool_calls 列表: {collected_tool_calls}")


def test_agent_executor():
    """测试完整的 Agent 执行流程"""
    print("\n" + "=" * 60)
    print("测试 6: 完整 Agent 执行流程（手动实现）")
    print("=" * 60)
    
    from langchain_core.messages import ToolMessage
    
    db = SQLDatabase.from_uri("sqlite:///./data/sample.db")
    llm = ChatTongyi(model="qwen3-max")
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()
    tool_dict = {tool.name: tool for tool in tools}
    
    llm_with_tools = llm.bind_tools(tools)
    
    system_prompt = f"""你是一个 SQL 数据库专家助手。

可用工具：
- sql_db_list_tables: 列出数据库中所有表
- sql_db_schema: 获取指定表的结构
- sql_db_query: 执行 SQL 查询
- sql_db_query_checker: 检查 SQL 语法

数据库方言: {db.dialect}

请按步骤操作：
1. 先查看有哪些表
2. 获取相关表的结构
3. 编写并执行查询
4. 返回结果给用户
"""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="哪个类别的销售总金额最高？")
    ]
    
    max_iterations = 5
    for i in range(max_iterations):
        print(f"\n=== 迭代 {i+1} ===")
        
        response = llm_with_tools.invoke(messages)
        print(f"AI 响应 content: {response.content[:300] if response.content else '(无内容)'}")
        print(f"tool_calls: {response.tool_calls}")
        
        messages.append(response)
        
        if not response.tool_calls:
            print("\n--- Agent 完成，最终回答 ---")
            print(response.content)
            break
        
        # 执行工具调用
        for tc in response.tool_calls:
            tool_name = tc['name']
            tool_args = tc['args']
            tool_id = tc['id']
            
            print(f"\n执行工具: {tool_name}")
            print(f"参数: {tool_args}")
            
            if tool_name in tool_dict:
                # 获取参数值
                if isinstance(tool_args, dict):
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
                else:
                    tool_input = tool_args
                
                try:
                    tool_result = tool_dict[tool_name].invoke(tool_input)
                    print(f"工具返回: {str(tool_result)[:300]}...")
                except Exception as e:
                    tool_result = f"Error: {e}"
                    print(f"工具错误: {e}")
                
                # 添加工具结果消息
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id
                ))
    
    print(f"\n--- 消息历史 ---")
    for i, msg in enumerate(messages):
        print(f"{i+1}. {type(msg).__name__}: {str(msg.content)[:100]}...")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("NL2SQL 组件测试")
    print("基于 Qwen3-max + LangChain SQLDatabaseToolkit")
    print("=" * 70 + "\n")
    
    try:
        # 1. 创建示例数据库
        create_sample_database()
        
        # 2. 测试 SQLDatabase
        db = test_sql_database()
        
        # 3. 测试 SQLDatabaseToolkit
        tools = test_sql_toolkit(db)
        
        # 4. 测试工具调用
        test_tools_invoke(tools)
        
        # 5. 测试 LLM 绑定工具
        test_llm_with_tools(tools)
        
        # 6. 测试流式输出
        test_streaming_with_tools(tools)
        
        # 7. 测试完整 Agent 流程
        test_agent_executor()
        
        print("\n" + "=" * 60)
        print("所有测试完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
