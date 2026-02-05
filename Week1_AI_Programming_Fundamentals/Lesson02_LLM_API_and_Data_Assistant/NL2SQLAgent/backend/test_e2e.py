"""
Phase 4 端到端测试
验证完整的用户流程：会话管理 -> 发送消息 -> 接收流式响应 -> 图表数据
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"


def process_event(event_type: str, data: str, events: dict):
    """处理单个 SSE 事件"""
    if event_type == "text":
        events["text"].append(data)
        print(f"  [TEXT] {data[:50]}..." if len(data) > 50 else f"  [TEXT] {data}")
    elif event_type == "thinking":
        events["thinking"].append(data)
        print(f"  [THINKING] {data}")
    elif event_type == "sql":
        events["sql"] = data
        print(f"  [SQL] {data[:80]}..." if len(data) > 80 else f"  [SQL] {data}")
    elif event_type == "data":
        try:
            events["data"] = json.loads(data)
            print(f"  [DATA] columns: {events['data'].get('columns')}, rows: {len(events['data'].get('rows', []))}")
        except json.JSONDecodeError:
            print(f"  [DATA] (parse error) {data[:50]}...")
    elif event_type == "chart":
        try:
            events["chart"] = json.loads(data)
            print(f"  [CHART] type: {events['chart'].get('type')}, title: {events['chart'].get('title')}")
        except json.JSONDecodeError:
            print(f"  [CHART] (parse error) {data[:50]}...")
    elif event_type == "done":
        events["done"] = True
        print("  [DONE]")
    elif event_type == "error":
        print(f"  [ERROR] {data}")


def test_full_flow():
    """测试完整的端到端流程"""
    print("\n" + "=" * 60)
    print("Phase 4 端到端测试")
    print("=" * 60)
    
    # 1. 创建新会话
    print("\n步骤 1: 创建新会话")
    print("-" * 40)
    response = requests.post(
        f"{BASE_URL}/api/sessions",
        json={"title": "E2E 测试会话"}
    )
    assert response.status_code == 201, f"创建会话失败: {response.status_code}"
    session = response.json()
    session_id = session["id"]
    print(f"✓ 会话已创建: {session_id}")
    print(f"  标题: {session['title']}")
    
    # 2. 发送查询消息
    print("\n步骤 2: 发送查询消息")
    print("-" * 40)
    query = "查询各个产品类别的销售总额，并按销售额排序"
    print(f"查询: {query}")
    
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={"session_id": session_id, "message": query},
        headers={"Accept": "text/event-stream"},
        stream=True
    )
    assert response.status_code == 200, f"聊天请求失败: {response.status_code}"
    
    # 3. 解析 SSE 响应
    print("\n步骤 3: 接收流式响应")
    print("-" * 40)
    
    events = {
        "text": [],
        "thinking": [],
        "sql": None,
        "data": None,
        "chart": None,
        "done": False
    }
    
    current_event = None
    data_lines = []
    
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("event: "):
            # 如果有待处理的事件，先处理它
            if current_event and data_lines:
                process_event(current_event, '\n'.join(data_lines), events)
            current_event = line[7:].strip()
            data_lines = []
        elif line.startswith("data: "):
            # 累积多行数据
            data_lines.append(line[6:])
        elif line == "":
            # 空行表示事件结束
            if current_event and data_lines:
                process_event(current_event, '\n'.join(data_lines), events)
                current_event = None
                data_lines = []
    
    # 处理最后一个事件
    if current_event and data_lines:
        process_event(current_event, '\n'.join(data_lines), events)
    
    # 4. 验证响应完整性
    print("\n步骤 4: 验证响应完整性")
    print("-" * 40)
    
    assert events["done"], "未收到 done 事件"
    print("✓ 收到完成事件")
    
    assert len(events["text"]) > 0, "未收到文本响应"
    print(f"✓ 收到 {len(events['text'])} 个文本片段")
    
    assert events["sql"], "未收到 SQL"
    print(f"✓ 收到 SQL 查询")
    
    # 验证 SQL 包含必要的关键字
    sql_lower = events["sql"].lower()
    assert "select" in sql_lower, "SQL 缺少 SELECT"
    assert "from sales" in sql_lower, "SQL 缺少 FROM sales"
    assert "group by" in sql_lower, "SQL 缺少 GROUP BY"
    print("✓ SQL 语句格式正确")
    
    if events["data"]:
        assert "columns" in events["data"], "数据缺少 columns"
        assert "rows" in events["data"], "数据缺少 rows"
        print(f"✓ 收到数据: {len(events['data']['rows'])} 行")
        print(f"  列名: {events['data']['columns']}")
    
    if events["chart"]:
        assert "type" in events["chart"], "图表配置缺少 type"
        assert "data" in events["chart"], "图表配置缺少 data"
        print(f"✓ 收到图表配置: {events['chart']['type']}")
    
    # 5. 验证会话消息已保存
    print("\n步骤 5: 验证会话消息持久化")
    print("-" * 40)
    
    response = requests.get(f"{BASE_URL}/api/sessions/{session_id}/messages")
    assert response.status_code == 200, f"获取消息失败: {response.status_code}"
    messages = response.json()
    
    assert len(messages) >= 2, f"消息数量不正确: {len(messages)}"
    print(f"✓ 会话中有 {len(messages)} 条消息")
    
    # 验证消息内容
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    assistant_msg = next((m for m in messages if m["role"] == "assistant"), None)
    
    assert user_msg, "未找到用户消息"
    assert assistant_msg, "未找到助手消息"
    print(f"✓ 用户消息: {user_msg['content'][:30]}...")
    print(f"✓ 助手消息: {assistant_msg['content'][:30]}...")
    
    if assistant_msg.get("sql_query"):
        print(f"✓ SQL 已保存到消息中")
    
    # 6. 清理测试会话
    print("\n步骤 6: 清理测试会话")
    print("-" * 40)
    
    response = requests.delete(f"{BASE_URL}/api/sessions/{session_id}")
    assert response.status_code in [200, 204], f"删除会话失败: {response.status_code}"
    print(f"✓ 测试会话已删除")
    
    print("\n" + "=" * 60)
    print("✅ 端到端测试全部通过！")
    print("=" * 60)
    
    return True


def test_multiple_queries():
    """测试多轮对话"""
    print("\n" + "=" * 60)
    print("多轮对话测试")
    print("=" * 60)
    
    # 创建会话
    response = requests.post(
        f"{BASE_URL}/api/sessions",
        json={"title": "多轮对话测试"}
    )
    session_id = response.json()["id"]
    print(f"会话 ID: {session_id}")
    
    queries = [
        "有哪些表?",
        "employees 表有什么字段?",
        "查询工资最高的员工"
    ]
    
    for i, query in enumerate(queries, 1):
        print(f"\n--- 查询 {i}: {query} ---")
        
        response = requests.post(
            f"{BASE_URL}/api/chat",
            json={"session_id": session_id, "message": query},
            headers={"Accept": "text/event-stream"},
            stream=True
        )
        
        text_parts = []
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = line[6:]
                if not data.startswith("{"):  # 非 JSON 数据就是文本
                    text_parts.append(data)
        
        full_text = "".join(text_parts)
        print(f"响应: {full_text[:100]}..." if len(full_text) > 100 else f"响应: {full_text}")
    
    # 验证消息数量
    response = requests.get(f"{BASE_URL}/api/sessions/{session_id}/messages")
    messages = response.json()
    print(f"\n总消息数: {len(messages)}")
    assert len(messages) >= 6, "多轮对话消息数量不正确"
    
    # 清理
    requests.delete(f"{BASE_URL}/api/sessions/{session_id}")
    print("✓ 多轮对话测试通过")
    
    return True


if __name__ == "__main__":
    try:
        test_full_flow()
        print()
        test_multiple_queries()
        print("\n" + "=" * 60)
        print("🎉 所有端到端测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ 测试错误: {e}")
        exit(1)
