from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Import database and models
from .database import init_db, Base
from .models import Conversation, Message  # Import models to register them
from .api.chat import router as chat_router
from .api.conversations import router as conversations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 初始化数据库
    print("Initializing database...")
    await init_db()
    print("Database initialized successfully!")
    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title="DeepSeek Chat API",
    description="A ChatGPT-like chat system powered by DeepSeek",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(chat_router)
app.include_router(conversations_router)


@app.get("/")
async def root():
    return {"message": "DeepSeek Chat API", "docs": "/docs"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint to verify API is running"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "service": "DeepSeek Chat API"
    }


@app.get("/api/models")
async def get_models():
    """Get available models"""
    return {
        "models": [
            {
                "id": "deepseek-chat",
                "name": "DeepSeek V3",
                "description": "快速对话模型，适合日常交流",
                "type": "chat",
                "thinking_enabled": False
            },
            {
                "id": "deepseek-chat-thinking",
                "name": "DeepSeek R1",
                "description": "推理模型，展示思考过程",
                "type": "reasoning",
                "thinking_enabled": True
            }
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
