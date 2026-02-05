"""
配置管理模块
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基础配置
    app_name: str = "Data Analysis Assistant"
    debug: bool = False
    
    # API 配置
    api_prefix: str = "/api"
    
    # CORS 配置
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    
    # 阿里云百炼 API 配置
    dashscope_api_key: str = ""
    
    # 数据库配置
    database_url: str = "sqlite:///./data/app.db"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
