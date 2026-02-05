"""
测试 Phase 3 API 接口
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"


def test_health():
    """测试健康检查"""
    print("=" * 50)
    print("测试 1: 健康检查 /health")
    print("=" * 50)
    
    resp = requests.get(f"{BASE_URL}/health")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
    return resp.status_code == 200


def test_root():
    """测试根路径"""
    print("\n" + "=" * 50)
    print("测试 2: 根路径 /")
    print("=" * 50)
    
    resp = requests.get(f"{BASE_URL}/")
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
    return resp.status_code == 200


def test_database_schema():
    """测试数据库结构"""
    print("\n" + "=" * 50)
    print("测试 3: 数据库结构 /api/database/schema")
    print("=" * 50)
    
    resp = requests.get(f"{BASE_URL}/api/database/schema")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Response: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
    else:
        print(f"Error: {resp.text}")
    return resp.status_code == 200


def test_sessions():
    """测试会话管理"""
    print("\n" + "=" * 50)
    print("测试 4: 会话管理")
    print("=" * 50)
    
    # 4.1 列出会话
    print("\n--- 4.1 列出会话 GET /api/sessions ---")
    resp = requests.get(f"{BASE_URL}/api/sessions")
    print(f"Status: {resp.status_code}")
    print(f"Sessions: {resp.json()}")
    
    # 4.2 创建会话
    print("\n--- 4.2 创建会话 POST /api/sessions ---")
    resp = requests.post(f"{BASE_URL}/api/sessions", json={"title": "测试会话"})
    print(f"Status: {resp.status_code}")
    if resp.status_code in [200, 201]:
        session = resp.json()
        print(f"Created: {json.dumps(session, indent=2, ensure_ascii=False)}")
        session_id = session["id"]
        
        # 4.3 获取会话详情
        print(f"\n--- 4.3 获取会话详情 GET /api/sessions/{session_id} ---")
        resp = requests.get(f"{BASE_URL}/api/sessions/{session_id}")
        print(f"Status: {resp.status_code}")
        print(f"Session: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
        
        return session_id
    else:
        print(f"Error: {resp.text}")
        return None


def test_chat(session_id: str):
    """测试聊天接口"""
    print("\n" + "=" * 50)
    print("测试 5: 聊天接口 POST /api/chat (SSE)")
    print("=" * 50)
    
    if not session_id:
        print("跳过：没有有效的会话 ID")
        return
    
    # 使用 SSE 流式请求
    resp = requests.post(
        f"{BASE_URL}/api/chat",
        json={"session_id": session_id, "message": "数据库里有哪些表？"},
        stream=True
    )
    
    print(f"Status: {resp.status_code}")
    print("SSE Events:")
    
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            print(f"  {line}")


def test_chat_query(session_id: str):
    """测试数据查询"""
    print("\n" + "=" * 50)
    print("测试 6: 数据查询 - 哪个类别销售最高")
    print("=" * 50)
    
    if not session_id:
        print("跳过：没有有效的会话 ID")
        return
    
    resp = requests.post(
        f"{BASE_URL}/api/chat",
        json={"session_id": session_id, "message": "哪个产品类别的销售总金额最高？"},
        stream=True
    )
    
    print(f"Status: {resp.status_code}")
    print("SSE Events:")
    
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            print(f"  {line}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Phase 3 API 测试")
    print("=" * 60 + "\n")
    
    try:
        test_health()
        test_root()
        test_database_schema()
        session_id = test_sessions()
        
        if session_id:
            test_chat(session_id)
            test_chat_query(session_id)
        
        print("\n" + "=" * 50)
        print("测试完成!")
        print("=" * 50)
        
    except requests.exceptions.ConnectionError as e:
        print(f"\n连接错误: 无法连接到 {BASE_URL}")
        print("请确保后端服务正在运行")
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
