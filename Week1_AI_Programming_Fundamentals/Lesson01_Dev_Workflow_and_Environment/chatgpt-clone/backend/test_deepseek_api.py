"""
DeepSeek API 测试脚本
测试目的：验证 API 输入输出规范，为前端接口对接提供参考
"""

from openai import OpenAI
import json

# DeepSeek API 配置
API_KEY = "sk-cc710e55d7354d99971ac42ff57f7dd4"
BASE_URL = "https://api.deepseek.com"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def test_chat_normal():
    """测试1: 普通对话模式 (deepseek-chat, 无思考)"""
    print("=" * 60)
    print("测试1: 普通对话模式 (deepseek-chat)")
    print("=" * 60)
    
    messages = [{"role": "user", "content": "用一句话介绍你自己"}]
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=True
    )
    
    print("\n--- 流式响应 chunk 详情 ---")
    content = ""
    chunk_count = 0
    
    for chunk in response:
        chunk_count += 1
        delta = chunk.choices[0].delta
        
        # 打印前5个和最后一个 chunk 的详细结构
        if chunk_count <= 5:
            print(f"\nChunk {chunk_count}:")
            print(f"  chunk.id: {chunk.id}")
            print(f"  chunk.model: {chunk.model}")
            print(f"  chunk.choices[0].index: {chunk.choices[0].index}")
            print(f"  chunk.choices[0].delta: {delta}")
            print(f"  chunk.choices[0].delta.role: {getattr(delta, 'role', None)}")
            print(f"  chunk.choices[0].delta.content: {getattr(delta, 'content', None)}")
            print(f"  chunk.choices[0].delta.reasoning_content: {getattr(delta, 'reasoning_content', None)}")
            print(f"  chunk.choices[0].finish_reason: {chunk.choices[0].finish_reason}")
        
        if delta.content:
            content += delta.content
    
    print(f"\n--- 统计 ---")
    print(f"总 chunk 数: {chunk_count}")
    print(f"\n--- 完整回复 ---")
    print(f"content: {content}")
    
    return content


def test_chat_with_thinking_via_model():
    """测试2: 思考模式 - 通过 model='deepseek-reasoner' 开启"""
    print("\n" + "=" * 60)
    print("测试2: 思考模式 (model=deepseek-reasoner)")
    print("=" * 60)
    
    messages = [{"role": "user", "content": "9.11 和 9.8 哪个更大？"}]
    
    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=messages,
        stream=True
    )
    
    print("\n--- 流式响应 chunk 详情 ---")
    reasoning_content = ""
    content = ""
    chunk_count = 0
    reasoning_chunks = 0
    content_chunks = 0
    
    for chunk in response:
        chunk_count += 1
        delta = chunk.choices[0].delta
        
        # 检查是否有 reasoning_content 属性
        has_reasoning = hasattr(delta, 'reasoning_content') and delta.reasoning_content
        has_content = hasattr(delta, 'content') and delta.content
        
        # 打印前10个 chunk 的详细结构
        if chunk_count <= 10:
            print(f"\nChunk {chunk_count}:")
            print(f"  delta.role: {getattr(delta, 'role', None)}")
            print(f"  delta.reasoning_content: {getattr(delta, 'reasoning_content', None)}")
            print(f"  delta.content: {getattr(delta, 'content', None)}")
            print(f"  finish_reason: {chunk.choices[0].finish_reason}")
        
        if has_reasoning:
            reasoning_content += delta.reasoning_content
            reasoning_chunks += 1
        
        if has_content:
            content += delta.content
            content_chunks += 1
    
    print(f"\n--- 统计 ---")
    print(f"总 chunk 数: {chunk_count}")
    print(f"reasoning chunk 数: {reasoning_chunks}")
    print(f"content chunk 数: {content_chunks}")
    
    print(f"\n--- 思考过程 (reasoning_content) ---")
    print(reasoning_content[:500] + "..." if len(reasoning_content) > 500 else reasoning_content)
    
    print(f"\n--- 最终回答 (content) ---")
    print(content)
    
    return reasoning_content, content


def test_chat_with_thinking_via_param():
    """测试3: 思考模式 - 通过 thinking 参数开启 (deepseek-chat + extra_body)"""
    print("\n" + "=" * 60)
    print("测试3: 思考模式 (deepseek-chat + thinking param)")
    print("=" * 60)
    
    messages = [{"role": "user", "content": "strawberry 这个单词里有几个字母 r？"}]
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=True,
        extra_body={"thinking": {"type": "enabled"}}
    )
    
    print("\n--- 流式响应 chunk 详情 ---")
    reasoning_content = ""
    content = ""
    chunk_count = 0
    reasoning_chunks = 0
    content_chunks = 0
    
    for chunk in response:
        chunk_count += 1
        delta = chunk.choices[0].delta
        
        has_reasoning = hasattr(delta, 'reasoning_content') and delta.reasoning_content
        has_content = hasattr(delta, 'content') and delta.content
        
        # 打印前10个 chunk 的详细结构
        if chunk_count <= 10:
            print(f"\nChunk {chunk_count}:")
            print(f"  delta.role: {getattr(delta, 'role', None)}")
            print(f"  delta.reasoning_content: {getattr(delta, 'reasoning_content', None)}")
            print(f"  delta.content: {getattr(delta, 'content', None)}")
            print(f"  finish_reason: {chunk.choices[0].finish_reason}")
        
        if has_reasoning:
            reasoning_content += delta.reasoning_content
            reasoning_chunks += 1
        
        if has_content:
            content += delta.content
            content_chunks += 1
    
    print(f"\n--- 统计 ---")
    print(f"总 chunk 数: {chunk_count}")
    print(f"reasoning chunk 数: {reasoning_chunks}")
    print(f"content chunk 数: {content_chunks}")
    
    print(f"\n--- 思考过程 (reasoning_content) ---")
    print(reasoning_content[:500] + "..." if len(reasoning_content) > 500 else reasoning_content)
    
    print(f"\n--- 最终回答 (content) ---")
    print(content)
    
    return reasoning_content, content


def test_multi_turn_conversation():
    """测试4: 多轮对话"""
    print("\n" + "=" * 60)
    print("测试4: 多轮对话 (验证消息格式)")
    print("=" * 60)
    
    # Turn 1
    messages = [{"role": "user", "content": "我叫小明"}]
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=True
    )
    
    content1 = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            content1 += chunk.choices[0].delta.content
    
    print(f"Turn 1 - User: 我叫小明")
    print(f"Turn 1 - Assistant: {content1}")
    
    # Turn 2
    messages.append({"role": "assistant", "content": content1})
    messages.append({"role": "user", "content": "我叫什么名字？"})
    
    print(f"\n发送的 messages 结构:")
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=True
    )
    
    content2 = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            content2 += chunk.choices[0].delta.content
    
    print(f"\nTurn 2 - User: 我叫什么名字？")
    print(f"Turn 2 - Assistant: {content2}")


def main():
    print("DeepSeek API 测试开始")
    print("API Key:", API_KEY[:10] + "..." + API_KEY[-4:])
    print("Base URL:", BASE_URL)
    
    # 测试1: 普通对话
    test_chat_normal()
    
    # 测试2: 思考模式 (via model)
    test_chat_with_thinking_via_model()
    
    # 测试3: 思考模式 (via param)
    test_chat_with_thinking_via_param()
    
    # 测试4: 多轮对话
    test_multi_turn_conversation()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    
    print("""
=== API 字段总结 ===

1. 普通对话模式 (deepseek-chat):
   - chunk.choices[0].delta.content: 回复内容
   - chunk.choices[0].delta.reasoning_content: None (不存在)

2. 思考模式 (deepseek-reasoner 或 thinking.type=enabled):
   - chunk.choices[0].delta.reasoning_content: 思考过程内容
   - chunk.choices[0].delta.content: 最终回答内容
   - 顺序: 先输出所有 reasoning_content，再输出 content

3. SSE 格式建议:
   - type: "reasoning" | "content" | "done" | "error"
   - data: 实际内容
""")


if __name__ == "__main__":
    main()
