"""
测试 Qwen3 API 的流式输出和函数调用功能
"""
import os

# 设置 API Key
os.environ["DASHSCOPE_API_KEY"] = "sk-89617ce8f26248d4b22523f3e362b0b6"

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool


def test_basic_chat():
    """测试基本对话"""
    print("=" * 50)
    print("测试 1: 基本对话")
    print("=" * 50)
    
    chat_llm = ChatTongyi(model="qwen3-max")
    
    messages = [
        SystemMessage(content="你是一个有帮助的助手。"),
        HumanMessage(content="你好，请用一句话介绍一下你自己")
    ]
    
    response = chat_llm.invoke(messages)
    print(f"响应内容: {response.content}")
    print(f"响应元数据: {response.response_metadata}")
    print(f"响应 ID: {response.id}")
    print()


def test_streaming():
    """测试流式输出"""
    print("=" * 50)
    print("测试 2: 流式输出")
    print("=" * 50)
    
    chat_llm = ChatTongyi(model="qwen-max", streaming=True)
    
    print("流式响应内容: ", end="")
    for chunk in chat_llm.stream([HumanMessage(content="用3句话介绍Python语言")]):
        print(f"\n--- Chunk ---")
        print(f"content: {chunk.content}")
        print(f"id: {chunk.id}")
        if chunk.response_metadata:
            print(f"response_metadata: {chunk.response_metadata}")
        if hasattr(chunk, 'additional_kwargs') and chunk.additional_kwargs:
            print(f"additional_kwargs: {chunk.additional_kwargs}")
    print()


@tool
def get_current_weather(location: str) -> str:
    """获取指定城市的天气信息
    
    Args:
        location: 城市名称，如 北京、上海
    """
    # 模拟天气数据
    weather_data = {
        "北京": "晴天，温度 25°C",
        "上海": "多云，温度 28°C",
        "杭州": "小雨，温度 22°C",
    }
    return weather_data.get(location, f"{location}：天气数据暂不可用")


@tool
def calculate(expression: str) -> str:
    """计算数学表达式
    
    Args:
        expression: 数学表达式，如 2+3*4
    """
    try:
        result = eval(expression)
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算错误: {e}"


def test_tool_calling():
    """测试函数调用"""
    print("=" * 50)
    print("测试 3: 函数调用 (Tool Calling)")
    print("=" * 50)
    
    llm = ChatTongyi(model="qwen3-max")
    
    # 绑定工具
    llm_with_tools = llm.bind_tools([get_current_weather, calculate])
    
    # 测试天气查询
    print("\n--- 测试天气查询 ---")
    msg = llm_with_tools.invoke("北京今天天气怎么样？")
    print(f"响应内容: {msg.content}")
    print(f"tool_calls: {msg.tool_calls}")
    print(f"additional_kwargs: {msg.additional_kwargs}")
    print(f"response_metadata: {msg.response_metadata}")
    
    # 测试计算
    print("\n--- 测试计算 ---")
    msg2 = llm_with_tools.invoke("计算 123 乘以 456 等于多少？")
    print(f"响应内容: {msg2.content}")
    print(f"tool_calls: {msg2.tool_calls}")
    print(f"additional_kwargs: {msg2.additional_kwargs}")
    print(f"response_metadata: {msg2.response_metadata}")
    print()


def test_streaming_with_tools():
    """测试带工具的流式输出"""
    print("=" * 50)
    print("测试 4: 带工具的流式输出")
    print("=" * 50)
    
    llm = ChatTongyi(model="qwen-max", streaming=True)
    llm_with_tools = llm.bind_tools([get_current_weather, calculate])
    
    print("流式响应（带工具）:")
    for chunk in llm_with_tools.stream("上海的天气如何？"):
        print(f"\n--- Chunk ---")
        print(f"content: {repr(chunk.content)}")
        print(f"id: {chunk.id}")
        if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
            print(f"tool_calls: {chunk.tool_calls}")
        if hasattr(chunk, 'tool_call_chunks') and chunk.tool_call_chunks:
            print(f"tool_call_chunks: {chunk.tool_call_chunks}")
        if chunk.additional_kwargs:
            print(f"additional_kwargs: {chunk.additional_kwargs}")
        if chunk.response_metadata:
            print(f"response_metadata: {chunk.response_metadata}")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Qwen3 API 测试")
    print("模型: qwen3-max")
    print("=" * 60 + "\n")
    
    try:
        test_basic_chat()
        test_streaming()
        test_tool_calling()
        test_streaming_with_tools()
        
        print("=" * 50)
        print("所有测试完成!")
        print("=" * 50)
    except Exception as e:
        print(f"测试出错: {e}")
        import traceback
        traceback.print_exc()
