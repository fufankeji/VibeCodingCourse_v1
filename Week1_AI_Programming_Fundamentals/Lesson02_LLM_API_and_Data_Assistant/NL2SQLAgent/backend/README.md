# Data Analysis Assistant - Backend

基于 FastAPI + LangChain + Qwen3 的智能数据分析助理后端服务。

## 快速开始

### 1. 创建虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

### 4. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/` | GET | 服务信息 |

## 项目结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI 入口
│   ├── config.py        # 配置管理
│   ├── api/             # API 路由 (Phase 3)
│   ├── core/            # 核心逻辑 (Phase 3)
│   ├── db/              # 数据库 (Phase 3)
│   └── schemas/         # Pydantic 模型 (Phase 3)
├── data/                # 数据文件
├── requirements.txt
├── .env.example
└── README.md
```
