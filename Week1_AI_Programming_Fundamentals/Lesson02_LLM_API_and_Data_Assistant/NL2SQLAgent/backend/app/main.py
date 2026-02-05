"""
FastAPI 应用入口
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api import chat, session, database
from app.db.connection import get_sql_database, ensure_data_dir

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：确保数据目录存在，初始化数据库
    ensure_data_dir()
    get_sql_database()  # 触发数据库初始化
    print("Application started, database initialized.")
    
    yield
    
    # 关闭时：清理资源
    print("Application shutting down.")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="智能数据分析助理 - 基于 LangChain + Qwen3 的自然语言数据库查询系统",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(session.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(database.router, prefix="/api")


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "message": "Service is running"}


@app.get("/")
async def root():
    """根路径"""
    return {
        "app": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "api_endpoints": {
            "sessions": "/api/sessions",
            "chat": "/api/chat",
            "database": "/api/database/schema",
        }
    }
