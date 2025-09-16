#!/usr/bin/env python3
"""
检查K线时间对齐和BOLL计算问题
"""
import sqlite3
import pandas as pd
from datetime import datetime, timezone
import numpy as np

def main():
    print("=== 开始检查时间对齐和BOLL计算问题 ===")
    
    try:
        conn = sqlite3.connect("trader.db")
        print("数据库连接成功")
        
        # 检查K线时间对齐
        check_kline_alignment(conn)
        
        # 检查BOLL计算
        check_boll_calculation(conn)
        
        # 检查币安时间格式
        check_binance_time_format()
        
    except Exception as e:
        print(f"程序执行出错: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def check_kline_alignment(conn):
    """检查K线时间对齐问题"""
    print("\n=== K线时间对齐检查 ===")
    
    try:
        # 获取最新的15分钟K线数据
        df = pd.read_sql_query("""
            SELECT open_time, close_time, close, volume, is_closed
            FROM klines 
            ORDER BY open_time DESC 
            LIMIT 20
        """, conn)
        
        if df.empty:
            print("没有K线数据")
            return
            
        print(f"最新20条K线数据:")
        for _, row in df.iterrows():
            open_dt = datetime.fromtimestamp(row['open_time']/1000, tz=timezone.utc)
            close_dt = datetime.fromtimestamp(row['close_time']/1000, tz=timezone.utc)
            print(f"开盘: {open_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                  f"收盘: {close_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                  f"价格: {row['close']} | 已收盘: {bool(row['is_closed'])}")
        
        # 检查15分钟对齐
        print("\n=== 15分钟对齐检查 ===")
        for _, row in df.head(5).iterrows():
            open_dt = datetime.fromtimestamp(row['open_time']/1000, tz=timezone.utc)
            minute = open_dt.minute
            is_aligned = minute % 15 == 0
            print(f"时间: {open_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                  f"分钟: {minute} | 15分钟对齐: {is_aligned}")
                  
    except Exception as e:
        print(f"检查K线对齐时出错: {e}")

def check_boll_calculation(conn):
    """检查BOLL计算"""
    print("\n=== BOLL计算检查 ===")
    
    try:
        # 获取K线数据用于计算BOLL
        df = pd.read_sql_query("""
            SELECT open_time, close
            FROM klines 
            WHERE is_closed = 1
            ORDER BY open_time DESC 
            LIMIT 50
        """, conn)
        
        if len(df) < 20:
            print("K线数据不足20条，无法计算BOLL")
            return
            
        # 反转数据顺序（从旧到新）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算BOLL
        window = 20
        multiplier = 2.0
        ddof = 1  # 当前配置
        
        df['ma'] = df['close'].rolling(window=window).mean()
        df['std'] = df['close'].rolling(window=window).std(ddof=ddof)
        df['up'] = df['ma'] + multiplier * df['std']
        df['dn'] = df['ma'] - multiplier * df['std']
        
        # 显示最新的BOLL计算结果
        latest = df.iloc[-1]
        print(f"最新BOLL计算结果:")
        print(f"时间: {datetime.fromtimestamp(latest['open_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"收盘价: {latest['close']:.2f}")
        print(f"MA: {latest['ma']:.2f}")
        print(f"STD: {latest['std']:.4f}")
        print(f"UP: {latest['up']:.2f}")
        print(f"DN: {latest['dn']:.2f}")
        
        # 对比数据库中的BOLL数据
        indicators_df = pd.read_sql_query("""
            SELECT open_time, ma, std, up, dn
            FROM indicators 
            ORDER BY open_time DESC 
            LIMIT 1
        """, conn)
        
        if not indicators_df.empty:
            db_data = indicators_df.iloc[0]
            print(f"\n数据库中的BOLL数据:")
            print(f"时间: {datetime.fromtimestamp(db_data['open_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"MA: {db_data['ma']:.2f}")
            print(f"STD: {db_data['std']:.4f}")
            print(f"UP: {db_data['up']:.2f}")
            print(f"DN: {db_data['dn']:.2f}")
            
            # 计算差异
            if latest['open_time'] == db_data['open_time']:
                print(f"\n差异分析:")
                print(f"MA差异: {abs(latest['ma'] - db_data['ma']):.4f}")
                print(f"STD差异: {abs(latest['std'] - db_data['std']):.6f}")
                print(f"UP差异: {abs(latest['up'] - db_data['up']):.4f}")
                print(f"DN差异: {abs(latest['dn'] - db_data['dn']):.4f}")
            else:
                print(f"时间不匹配，无法对比")
        else:
            print("数据库中没有BOLL指标数据")
            
    except Exception as e:
        print(f"检查BOLL计算时出错: {e}")

def check_binance_time_format():
    """检查币安时间格式"""
    print("\n=== 币安时间格式检查 ===")
    
    # 币安15分钟K线应该在UTC时间的00:00, 00:15, 00:30, 00:45开始
    now_utc = datetime.now(timezone.utc)
    print(f"当前UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # 计算下一个15分钟对齐时间
    current_minute = now_utc.minute
    next_15min = ((current_minute // 15) + 1) * 15
    if next_15min >= 60:
        next_hour = now_utc.hour + 1
        next_minute = 0
    else:
        next_hour = now_utc.hour
        next_minute = next_15min
    
    print(f"下一个15分钟对齐时间应该是: {next_hour:02d}:{next_minute:02d}")

if __name__ == "__main__":
    main()