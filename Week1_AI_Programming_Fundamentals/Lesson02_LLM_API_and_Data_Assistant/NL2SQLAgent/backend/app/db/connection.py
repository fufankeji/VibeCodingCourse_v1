"""
数据库连接管理模块
"""
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional

from langchain_community.utilities import SQLDatabase

from app.config import get_settings


def get_db_path() -> str:
    """获取数据库文件路径"""
    settings = get_settings()
    db_url = settings.database_url
    
    # 从 sqlite:///./data/app.db 提取路径
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "")
    return "./data/app.db"


def ensure_data_dir():
    """确保数据目录存在"""
    db_path = get_db_path()
    data_dir = os.path.dirname(db_path)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)


@lru_cache
def get_sql_database() -> SQLDatabase:
    """
    获取 SQLDatabase 实例（用于 LangChain Agent）
    
    Returns:
        SQLDatabase 实例
    """
    settings = get_settings()
    ensure_data_dir()
    
    db_path = get_db_path()
    
    # 检查是否需要初始化示例数据
    need_init = False
    if not os.path.exists(db_path):
        need_init = True
    else:
        # 检查 sales 表是否存在
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales'")
        if not cursor.fetchone():
            need_init = True
        conn.close()
    
    if need_init:
        init_sample_database(db_path)
    
    return SQLDatabase.from_uri(settings.database_url)


def get_raw_connection() -> sqlite3.Connection:
    """
    获取原生 SQLite 连接（用于会话存储等）
    
    Returns:
        sqlite3.Connection
    """
    ensure_data_dir()
    db_path = get_db_path()
    return sqlite3.connect(db_path, check_same_thread=False)


def init_sample_database(db_path: str):
    """
    初始化示例数据库
    
    创建销售数据表并插入示例数据
    """
    print(f"Initializing sample database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建销售表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            sale_date DATE NOT NULL,
            region TEXT NOT NULL
        )
    """)
    
    # 创建员工表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            position TEXT NOT NULL,
            salary REAL NOT NULL,
            hire_date DATE NOT NULL
        )
    """)
    
    # 创建会话表（用于持久化）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 创建消息表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sql_query TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        )
    """)
    
    # 插入销售示例数据
    sales_data = [
        ('笔记本电脑', '电子产品', 15, 5999.00, '2024-01-15', '华东'),
        ('无线鼠标', '电子产品', 80, 99.00, '2024-01-15', '华东'),
        ('机械键盘', '电子产品', 45, 299.00, '2024-01-16', '华北'),
        ('显示器', '电子产品', 20, 1299.00, '2024-01-17', '华南'),
        ('办公椅', '家具', 30, 599.00, '2024-01-18', '华东'),
        ('办公桌', '家具', 15, 899.00, '2024-01-18', '华北'),
        ('打印纸', '办公用品', 200, 29.00, '2024-01-19', '华南'),
        ('签字笔', '办公用品', 500, 5.00, '2024-01-19', '华东'),
        ('文件夹', '办公用品', 300, 15.00, '2024-01-20', '华北'),
        ('台灯', '家具', 40, 199.00, '2024-01-20', '华南'),
        ('平板电脑', '电子产品', 25, 3299.00, '2024-01-21', '华东'),
        ('耳机', '电子产品', 60, 199.00, '2024-01-22', '华北'),
        ('投影仪', '电子产品', 8, 2999.00, '2024-01-23', '华南'),
        ('书架', '家具', 12, 399.00, '2024-01-24', '华东'),
        ('白板', '办公用品', 25, 149.00, '2024-01-25', '华北'),
    ]
    
    cursor.executemany(
        "INSERT INTO sales (product_name, category, quantity, price, sale_date, region) VALUES (?, ?, ?, ?, ?, ?)",
        sales_data
    )
    
    # 插入员工示例数据
    employees_data = [
        ('张伟', '技术部', '高级工程师', 25000.00, '2020-03-15'),
        ('李娜', '技术部', '工程师', 18000.00, '2021-06-20'),
        ('王芳', '市场部', '市场经理', 22000.00, '2019-08-10'),
        ('刘洋', '市场部', '市场专员', 12000.00, '2022-01-05'),
        ('陈明', '财务部', '财务主管', 20000.00, '2018-11-20'),
        ('赵丽', '财务部', '会计', 15000.00, '2021-04-15'),
        ('孙强', '人事部', '人事经理', 18000.00, '2020-07-01'),
        ('周杰', '技术部', '技术总监', 35000.00, '2017-02-28'),
    ]
    
    cursor.executemany(
        "INSERT INTO employees (name, department, position, salary, hire_date) VALUES (?, ?, ?, ?, ?)",
        employees_data
    )
    
    conn.commit()
    conn.close()
    
    print(f"Sample database initialized with {len(sales_data)} sales records and {len(employees_data)} employees.")


def get_database_schema() -> dict:
    """
    获取数据库结构信息
    
    Returns:
        包含表结构的字典
    """
    db = get_sql_database()
    tables = db.get_usable_table_names()
    
    schema = {
        "dialect": db.dialect,
        "tables": []
    }
    
    conn = get_raw_connection()
    cursor = conn.cursor()
    
    for table in tables:
        # 跳过内部表
        if table.startswith("chat_"):
            continue
            
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        
        # 获取行数
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        row_count = cursor.fetchone()[0]
        
        table_info = {
            "name": table,
            "columns": [
                {
                    "name": col[1],
                    "type": col[2],
                    "nullable": not col[3],
                    "primary_key": bool(col[5])
                }
                for col in columns
            ],
            "row_count": row_count
        }
        schema["tables"].append(table_info)
    
    conn.close()
    return schema
