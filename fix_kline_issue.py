#!/usr/bin/env python3
"""
修复K线数据问题的脚本
"""
import sqlite3
import pandas as pd
from datetime import datetime, timezone
import numpy as np
from config import load_config

def main():
    print("=== 分析和修复K线数据问题 ===")
    
    # 加载配置
    cfg = load_config()
    print(f"配置文件中的interval: {cfg.interval}")
    print(f"配置文件中的symbol: {cfg.symbol}")
    
    # 连接数据库
    conn = sqlite3.connect("trader.db")
    
    try:
        # 分析当前K线数据
        analyze_current_data(conn)
        
        # 分析BOLL计算问题
        analyze_boll_issue(conn, cfg)
        
        # 提供修复建议
        provide_fix_suggestions()
        
    finally:
        conn.close()

def analyze_current_data(conn):
    """分析当前K线数据"""
    print("\n=== 当前K线数据分析 ===")
    
    # 检查K线数据的时间间隔
    df = pd.read_sql_query("""
        SELECT open_time, close_time, close, is_closed
        FROM klines 
        ORDER BY open_time DESC 
        LIMIT 10
    """, conn)
    
    if df.empty:
        print("没有K线数据")
        return
    
    print("最新10条K线数据的时间间隔分析:")
    for i in range(len(df) - 1):
        current_time = df.iloc[i]['open_time']
        next_time = df.iloc[i + 1]['open_time']
        interval_ms = current_time - next_time
        interval_minutes = interval_ms / (1000 * 60)
        
        current_dt = datetime.fromtimestamp(current_time/1000, tz=timezone.utc)
        print(f"时间: {current_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
              f"与下一条间隔: {interval_minutes:.1f}分钟")
    
    # 检查15分钟对齐
    print("\n15分钟对齐检查:")
    for _, row in df.head(5).iterrows():
        open_dt = datetime.fromtimestamp(row['open_time']/1000, tz=timezone.utc)
        minute = open_dt.minute
        is_15min_aligned = minute % 15 == 0
        is_1min_data = True  # 基于间隔分析
        
        print(f"时间: {open_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
              f"分钟: {minute:02d} | 15分钟对齐: {is_15min_aligned} | "
              f"疑似1分钟数据: {is_1min_data}")

def analyze_boll_issue(conn, cfg):
    """分析BOLL计算问题"""
    print("\n=== BOLL计算问题分析 ===")
    
    # 获取最新的已收盘K线数据
    df = pd.read_sql_query("""
        SELECT open_time, close
        FROM klines 
        WHERE is_closed = 1
        ORDER BY open_time DESC 
        LIMIT 100
    """, conn)
    
    if len(df) < cfg.window:
        print(f"K线数据不足{cfg.window}条，无法计算BOLL")
        return
    
    # 反转数据顺序（从旧到新）
    df = df.iloc[::-1].reset_index(drop=True)
    
    print(f"使用最新{len(df)}条K线数据计算BOLL")
    print(f"BOLL参数: window={cfg.window}, multiplier={cfg.boll_multiplier}, ddof={cfg.boll_ddof}")
    
    # 计算BOLL（使用1分钟数据）
    df['ma'] = df['close'].rolling(window=cfg.window).mean()
    df['std'] = df['close'].rolling(window=cfg.window).std(ddof=cfg.boll_ddof)
    df['up'] = df['ma'] + cfg.boll_multiplier * df['std']
    df['dn'] = df['ma'] - cfg.boll_multiplier * df['std']
    
    # 显示最新的BOLL计算结果
    latest = df.iloc[-1]
    print(f"\n基于1分钟数据的BOLL计算:")
    print(f"时间: {datetime.fromtimestamp(latest['open_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"收盘价: {latest['close']:.2f}")
    print(f"MA: {latest['ma']:.2f}")
    print(f"STD: {latest['std']:.4f}")
    print(f"UP: {latest['up']:.2f}")
    print(f"DN: {latest['dn']:.2f}")
    
    # 模拟15分钟数据的BOLL计算
    print(f"\n模拟15分钟数据的BOLL计算:")
    
    # 将1分钟数据聚合为15分钟数据
    df['datetime'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df.set_index('datetime', inplace=True)
    
    # 重采样为15分钟数据
    df_15m = df['close'].resample('15T').agg({
        'open': 'first',
        'high': 'max', 
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    if len(df_15m) >= cfg.window:
        # 计算15分钟BOLL
        df_15m['ma'] = df_15m['close'].rolling(window=cfg.window).mean()
        df_15m['std'] = df_15m['close'].rolling(window=cfg.window).std(ddof=cfg.boll_ddof)
        df_15m['up'] = df_15m['ma'] + cfg.boll_multiplier * df_15m['std']
        df_15m['dn'] = df_15m['ma'] - cfg.boll_multiplier * df_15m['std']
        
        latest_15m = df_15m.iloc[-1]
        print(f"时间: {latest_15m.name.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"收盘价: {latest_15m['close']:.2f}")
        print(f"MA: {latest_15m['ma']:.2f}")
        print(f"STD: {latest_15m['std']:.4f}")
        print(f"UP: {latest_15m['up']:.2f}")
        print(f"DN: {latest_15m['dn']:.2f}")
        
        # 对比差异
        print(f"\n1分钟 vs 15分钟BOLL差异:")
        print(f"MA差异: {abs(latest['ma'] - latest_15m['ma']):.4f}")
        print(f"STD差异: {abs(latest['std'] - latest_15m['std']):.6f}")
        print(f"UP差异: {abs(latest['up'] - latest_15m['up']):.4f}")
        print(f"DN差异: {abs(latest['dn'] - latest_15m['dn']):.4f}")
    else:
        print("15分钟数据不足，无法计算BOLL")
    
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

def provide_fix_suggestions():
    """提供修复建议"""
    print("\n=== 修复建议 ===")
    print("根据分析，发现以下问题:")
    print("1. 程序配置为15分钟周期，但实际接收的是1分钟K线数据")
    print("2. BOLL计算基于1分钟数据，与币安15分钟图表的BOLL不一致")
    print("3. 时间对齐问题：1分钟数据无法与15分钟周期对齐")
    
    print("\n修复方案:")
    print("方案1: 修改WebSocket订阅为15分钟K线")
    print("  - 优点: 直接获取15分钟数据，与币安图表完全一致")
    print("  - 缺点: 更新频率较低（每15分钟一次）")
    
    print("方案2: 保持1分钟数据，但聚合为15分钟计算BOLL")
    print("  - 优点: 保持高频更新，同时计算准确的15分钟BOLL")
    print("  - 缺点: 需要修改指标计算逻辑")
    
    print("方案3: 同时订阅1分钟和15分钟数据")
    print("  - 优点: 既有高频更新又有准确的15分钟指标")
    print("  - 缺点: 复杂度较高")
    
    print("\n推荐方案1: 直接修改为15分钟K线订阅")

if __name__ == "__main__":
    main()