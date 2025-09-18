#!/usr/bin/env python3
"""
数据库迁移脚本：添加新的策略状态字段
"""
import sqlite3
import sys
import os

def migrate_database(db_path: str):
    """迁移数据库，添加新的字段"""
    print(f"开始迁移数据库: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(strategy_state)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 添加新字段
        if 'breakout_up' not in columns:
            print("添加 breakout_up 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN breakout_up INTEGER DEFAULT 0")
        
        if 'breakout_dn' not in columns:
            print("添加 breakout_dn 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN breakout_dn INTEGER DEFAULT 0")
        
        if 'last_close_price' not in columns:
            print("添加 last_close_price 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN last_close_price REAL")
        
        conn.commit()
        conn.close()
        print("数据库迁移完成!")
        
    except Exception as e:
        print(f"迁移失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    db_path = "trading.db"
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        sys.exit(1)
    
    migrate_database(db_path)