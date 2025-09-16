#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def analyze_trades():
    conn = sqlite3.connect('trader.db')
    conn.row_factory = sqlite3.Row
    
    print("=== 分析交易记录和仓位状态 ===")
    
    # 获取所有交易记录，按时间排序
    cur = conn.execute('''
        SELECT 
            datetime(ts/1000, 'unixepoch', 'localtime') as time,
            ts,
            side, 
            qty, 
            price,
            order_id,
            status
        FROM trades 
        ORDER BY ts ASC
    ''')
    
    trades = cur.fetchall()
    
    print(f"总共 {len(trades)} 条交易记录\n")
    
    # 模拟仓位状态
    position = "flat"  # flat, long, short
    position_qty = 0.0
    
    print("=== 交易序列分析 ===")
    for i, trade in enumerate(trades):
        side = trade['side']
        qty = float(trade['qty']) if trade['qty'] else 0.0
        
        print(f"{i+1:2d}. {trade['time']} | {side:12} | {qty:8.3f} | 当前仓位: {position}")
        
        # 分析每笔交易对仓位的影响
        if side in ["BUY", "BUY_OPEN"]:
            if position == "flat":
                position = "long"
                position_qty = qty
                print(f"    -> 开多仓，仓位变为: {position} ({position_qty:.3f})")
            elif position == "short":
                print(f"    ❌ 错误：已有空仓 ({position_qty:.3f})，不应该再开多仓！")
            else:
                print(f"    ❌ 错误：已有多仓 ({position_qty:.3f})，不应该再开多仓！")
                
        elif side in ["SELL", "SELL_OPEN"]:
            if position == "flat":
                position = "short"
                position_qty = qty
                print(f"    -> 开空仓，仓位变为: {position} ({position_qty:.3f})")
            elif position == "long":
                print(f"    ❌ 错误：已有多仓 ({position_qty:.3f})，不应该再开空仓！")
            else:
                print(f"    ❌ 错误：已有空仓 ({position_qty:.3f})，不应该再开空仓！")
                
        elif side == "SELL_CLOSE":
            if position == "long":
                position = "flat"
                position_qty = 0.0
                print(f"    -> 平多仓，仓位变为: {position}")
            else:
                print(f"    ❌ 错误：当前仓位是 {position}，不应该平多仓！")
                
        elif side == "SELL_STOP_LOSS":
            if position == "long":
                position = "flat"
                position_qty = 0.0
                print(f"    -> 多仓止损，仓位变为: {position}")
            else:
                print(f"    ❌ 错误：当前仓位是 {position}，不应该多仓止损！")
                
        elif side == "BUY_CLOSE":
            if position == "short":
                position = "flat"
                position_qty = 0.0
                print(f"    -> 平空仓，仓位变为: {position}")
            else:
                print(f"    ❌ 错误：当前仓位是 {position}，不应该平空仓！")
                
        elif side == "BUY_STOP_LOSS":
            if position == "short":
                position = "flat"
                position_qty = 0.0
                print(f"    -> 空仓止损，仓位变为: {position}")
            else:
                print(f"    ❌ 错误：当前仓位是 {position}，不应该空仓止损！")
        
        print()
    
    # 检查策略状态表
    print("=== 策略状态表 ===")
    try:
        cur_state = conn.execute('SELECT * FROM strategy_state ORDER BY ts DESC LIMIT 10')
        states = cur_state.fetchall()
        for state in states:
            print(f"{datetime.fromtimestamp(state['ts']/1000)} | {state['state']}")
    except Exception as e:
        print(f"无法读取策略状态表: {e}")
    
    conn.close()

if __name__ == "__main__":
    analyze_trades()