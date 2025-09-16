#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def check_data():
    conn = sqlite3.connect('trader.db')
    cursor = conn.cursor()
    
    print("=== 最新的K线数据 ===")
    cursor.execute("""
        SELECT datetime(open_time/1000, 'unixepoch', 'localtime') as time, 
               open_time, close, volume 
        FROM klines 
        ORDER BY open_time DESC 
        LIMIT 10
    """)
    klines = cursor.fetchall()
    for row in klines:
        print(f"时间: {row[0]}, 开盘时间戳: {row[1]}, 收盘价: {row[2]}, 成交量: {row[3]}")
    
    if len(klines) >= 2:
        time_diff = (klines[0][1] - klines[1][1]) / 1000 / 60  # 转换为分钟
        print(f"\nK线间隔: {time_diff} 分钟")
    
    print("\n=== 最新的BOLL指标数据 ===")
    cursor.execute("""
        SELECT datetime(open_time/1000, 'unixepoch', 'localtime') as time,
               ma, std, up, dn
        FROM indicators 
        ORDER BY open_time DESC 
        LIMIT 5
    """)
    indicators = cursor.fetchall()
    for row in indicators:
        print(f"时间: {row[0]}, MA: {row[1]:.2f}, STD: {row[2]:.4f}, UP: {row[3]:.2f}, DN: {row[4]:.2f}")
    
    conn.close()

if __name__ == "__main__":
    check_data()