#!/usr/bin/env python3
"""
测试新的全部平仓功能
"""
import os
import sys
from dotenv import load_dotenv
from trader import Trader
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_position_functions():
    """测试仓位相关功能"""
    # 加载环境变量
    load_dotenv()
    
    # 初始化交易器
    trader = Trader()
    symbol = "ETHUSDT"
    
    print("=== 测试仓位查询功能 ===")
    try:
        qty, direction = trader.get_position_quantity(symbol)
        print(f"当前仓位: {symbol}")
        print(f"数量: {qty}")
        print(f"方向: {direction}")
        
        if direction != "flat":
            print(f"\n检测到 {direction} 仓位 {qty}")
            
            # 询问用户是否要测试平仓
            response = input(f"是否要测试全部平仓功能? (y/n): ").lower().strip()
            if response == 'y':
                print("\n=== 测试市价全部平仓功能 ===")
                order = trader.close_all_position(symbol)
                if order:
                    print(f"市价全部平仓成功: {order}")
                    
                    # 再次检查仓位
                    qty_after, direction_after = trader.get_position_quantity(symbol)
                    print(f"平仓后仓位: 数量={qty_after}, 方向={direction_after}")
                else:
                    print("市价全部平仓失败")
            else:
                print("跳过平仓测试")
        else:
            print("当前没有持仓，无法测试平仓功能")
            print("建议先手动开仓后再测试")
            
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        logging.error(f"测试错误: {e}")

def test_stop_market_close():
    """测试STOP_MARKET全部平仓功能"""
    load_dotenv()
    trader = Trader()
    symbol = "ETHUSDT"
    
    print("\n=== 测试STOP_MARKET全部平仓功能 ===")
    try:
        qty, direction = trader.get_position_quantity(symbol)
        if direction != "flat":
            response = input(f"是否要测试STOP_MARKET全部平仓功能? (y/n): ").lower().strip()
            if response == 'y':
                order = trader.close_all_position_with_stop_market(symbol)
                if order:
                    print(f"STOP_MARKET全部平仓成功: {order}")
                    
                    # 再次检查仓位
                    qty_after, direction_after = trader.get_position_quantity(symbol)
                    print(f"平仓后仓位: 数量={qty_after}, 方向={direction_after}")
                else:
                    print("STOP_MARKET全部平仓失败")
        else:
            print("当前没有持仓，无法测试STOP_MARKET平仓功能")
            
    except Exception as e:
        print(f"STOP_MARKET测试过程中出现错误: {e}")
        logging.error(f"STOP_MARKET测试错误: {e}")

if __name__ == "__main__":
    print("开始测试新的平仓功能...")
    print("注意: 这是真实交易测试，请确保你了解风险!")
    
    # 确认用户想要继续
    confirm = input("确认要进行真实交易测试吗? (yes/no): ").lower().strip()
    if confirm != 'yes':
        print("测试已取消")
        sys.exit(0)
    
    test_position_functions()
    test_stop_market_close()
    
    print("\n测试完成!")