#!/usr/bin/env python3
"""
清理数据库中的1分钟K线数据，为15分钟数据做准备
"""
import sqlite3
from datetime import datetime, timezone

def main():
    print("=== 清理数据库中的1分钟K线数据 ===")
    
    conn = sqlite3.connect("trader.db")
    cursor = conn.cursor()
    
    try:
        # 检查当前数据量
        cursor.execute("SELECT COUNT(*) FROM klines")
        kline_count = cursor.fetchone()[0]
        print(f"当前K线数据条数: {kline_count}")
        
        cursor.execute("SELECT COUNT(*) FROM indicators")
        indicator_count = cursor.fetchone()[0]
        print(f"当前指标数据条数: {indicator_count}")
        
        if kline_count > 0:
            # 显示最新和最旧的数据时间
            cursor.execute("SELECT MIN(open_time), MAX(open_time) FROM klines")
            min_time, max_time = cursor.fetchone()
            
            min_dt = datetime.fromtimestamp(min_time/1000, tz=timezone.utc)
            max_dt = datetime.fromtimestamp(max_time/1000, tz=timezone.utc)
            
            print(f"数据时间范围: {min_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} 到 {max_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        # 询问是否清理
        response = input("\n是否清理所有K线和指标数据？这将删除所有历史数据。(y/N): ")
        
        if response.lower() == 'y':
            # 清理K线数据
            cursor.execute("DELETE FROM klines")
            print(f"已删除 {cursor.rowcount} 条K线数据")
            
            # 清理指标数据
            cursor.execute("DELETE FROM indicators")
            print(f"已删除 {cursor.rowcount} 条指标数据")
            
            # 提交更改
            conn.commit()
            print("数据库清理完成！")
            
            # 验证清理结果
            cursor.execute("SELECT COUNT(*) FROM klines")
            remaining_klines = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM indicators")
            remaining_indicators = cursor.fetchone()[0]
            
            print(f"清理后K线数据条数: {remaining_klines}")
            print(f"清理后指标数据条数: {remaining_indicators}")
            
        else:
            print("取消清理操作")
            
    except Exception as e:
        print(f"清理过程中出错: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()