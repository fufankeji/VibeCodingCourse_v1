# 智能数据分析助理

基于 LangChain + FastAPI + React 构建的智能数据分析系统，接入阿里云百炼 Qwen3 模型，实现自然语言查询数据库并实时可视化展示。

## 项目结构

```
Lesson02_LLM_API_and_Data_Assistant/
├── backend/                    # 后端服务 (FastAPI + LangChain)
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   └── config.py          # 配置管理
│   ├── requirements.txt
│   └── README.md
├── frontend/                   # 前端应用 (React + TypeScript)
│   ├── src/
│   │   ├── App.tsx            # 主应用
│   │   └── main.tsx           # 入口
│   ├── package.json
│   └── README.md
└── README.md
```

## 快速开始

### 1. 启动后端服务

```bash
cd backend

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY

# 启动服务
uvicorn app.main:app --reload --port 8000
```

### 2. 启动前端应用

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 3. 访问应用

- 前端: http://localhost:5173
- 后端 API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| LLM | 阿里云百炼 Qwen3 | langchain-community[tongyi] |
| 后端框架 | FastAPI | 异步、SSE 支持 |
| Agent 框架 | LangChain | SQL Agent + Memory |
| 数据库 | SQLite3 | 轻量、无需部署 |
| 前端框架 | React 18 | Vite 构建 |
| 状态管理 | Zustand | 轻量简洁 |
| UI 组件 | Tailwind CSS | 现代美观 |
| 图表库 | ECharts | 功能丰富 |

## 开发阶段

- [x] **Phase 1**: 搭建前后端基础框架
- [ ] **Phase 2**: 前端 UI 开发
- [ ] **Phase 3**: 后端接口开发
- [ ] **Phase 4**: 前后端联调

## License

MIT
