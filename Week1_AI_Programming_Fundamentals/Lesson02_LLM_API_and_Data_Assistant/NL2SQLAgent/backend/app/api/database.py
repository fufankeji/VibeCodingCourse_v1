"""
数据库信息 API 路由
"""
from fastapi import APIRouter

from app.db.connection import get_database_schema, get_sql_database
from app.schemas.chat import DatabaseSchema

router = APIRouter(prefix="/database", tags=["database"])


@router.get("/schema", response_model=DatabaseSchema)
async def get_schema():
    """
    获取数据库结构信息
    
    Returns:
        数据库表结构
    """
    schema = get_database_schema()
    return schema


@router.get("/tables")
async def list_tables():
    """
    获取数据库表列表
    
    Returns:
        表名列表
    """
    db = get_sql_database()
    tables = db.get_usable_table_names()
    
    # 过滤内部表
    public_tables = [t for t in tables if not t.startswith("chat_")]
    
    return {"tables": public_tables}


@router.get("/tables/{table_name}")
async def get_table_info(table_name: str):
    """
    获取指定表的详细信息
    
    Args:
        table_name: 表名
    
    Returns:
        表结构和示例数据
    """
    db = get_sql_database()
    
    # 获取表结构
    table_info = db.get_table_info([table_name])
    
    # 获取示例数据
    sample_data = db.run(f"SELECT * FROM {table_name} LIMIT 5")
    
    return {
        "name": table_name,
        "schema": table_info,
        "sample_data": sample_data
    }
