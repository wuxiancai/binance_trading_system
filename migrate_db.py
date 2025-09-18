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
        
        # 检查strategy_state表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_state'")
        if not cursor.fetchone():
            print("错误: strategy_state表不存在，请先运行主程序创建表结构")
            sys.exit(1)
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(strategy_state)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"当前字段: {columns}")
        
        changes_made = False
        
        # 添加新字段
        if 'breakout_up' not in columns:
            print("添加 breakout_up 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN breakout_up INTEGER DEFAULT 0")
            changes_made = True
        else:
            print("breakout_up 字段已存在")
        
        if 'breakout_dn' not in columns:
            print("添加 breakout_dn 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN breakout_dn INTEGER DEFAULT 0")
            changes_made = True
        else:
            print("breakout_dn 字段已存在")
        
        if 'last_close_price' not in columns:
            print("添加 last_close_price 字段...")
            cursor.execute("ALTER TABLE strategy_state ADD COLUMN last_close_price REAL")
            changes_made = True
        else:
            print("last_close_price 字段已存在")
        
        if changes_made:
            conn.commit()
            print("数据库迁移完成!")
        else:
            print("所有字段都已存在，无需迁移")
        
        # 验证迁移结果
        cursor.execute("PRAGMA table_info(strategy_state)")
        final_columns = [row[1] for row in cursor.fetchall()]
        print(f"迁移后字段: {final_columns}")
        
        conn.close()
        
    except Exception as e:
        print(f"迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    db_path = "trader.db"  # 修复默认数据库文件名
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        sys.exit(1)
    
    migrate_database(db_path)