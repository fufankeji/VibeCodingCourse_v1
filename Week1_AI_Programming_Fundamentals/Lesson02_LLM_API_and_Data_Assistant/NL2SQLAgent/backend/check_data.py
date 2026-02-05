"""查看数据库数据"""
import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'chat_%'")
tables = cursor.fetchall()

print('=' * 60)
print('数据库表结构和数据')
print('=' * 60)

for (table,) in tables:
    print(f'\n📊 表: {table}')
    print('-' * 40)
    
    # 获取列信息
    cursor.execute(f'PRAGMA table_info({table})')
    columns = cursor.fetchall()
    col_names = [col[1] for col in columns]
    print(f'列: {col_names}')
    
    # 获取数据
    cursor.execute(f'SELECT * FROM {table}')
    rows = cursor.fetchall()
    print(f'行数: {len(rows)}')
    print()
    
    # 打印数据
    for row in rows:
        print(f'  {row}')

conn.close()
