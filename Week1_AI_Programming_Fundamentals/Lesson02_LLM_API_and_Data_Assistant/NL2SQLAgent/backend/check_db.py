import sqlite3
import os

db_path = "./data/app.db"
print(f"Database path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

# 删除旧数据库
if os.path.exists(db_path):
    os.remove(db_path)
    print("Old database removed.")

# 重新初始化
from app.db.connection import init_sample_database, get_sql_database

init_sample_database(db_path)

# 验证
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\nTables created: {tables}")

for table in tables:
    table_name = table[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"  {table_name}: {count} rows")

conn.close()

# 测试 SQLDatabase
print("\nTesting SQLDatabase...")
db = get_sql_database()
print(f"Dialect: {db.dialect}")
print(f"Tables: {db.get_usable_table_names()}")
