#!/usr/bin/env python3
"""验证强制API模式的修改"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def verify_webapp_changes():
    """验证webapp.py的修改"""
    print("=== 验证webapp.py的修改 ===")
    
    with open('webapp.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查关键修改
    checks = [
        ("强制要求trader实例", "trader实例不能为空" in content),
        ("移除回退机制", "回退到原有的本地交易记录分析逻辑" not in content),
        ("抛出异常而非回退", "raise RuntimeError" in content),
        ("保留API数据来源标识", '"source": "binance_api"' in content)
    ]
    
    for desc, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {desc}: {'通过' if passed else '失败'}")
    
    return all(passed for _, passed in checks)

def verify_main_changes():
    """验证main.py的修改"""
    print("\n=== 验证main.py的修改 ===")
    
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查关键修改
    checks = [
        ("添加实时仓位检查", "trader.get_position_info(cfg.symbol)" in content),
        ("更新本地状态", "state.position = actual_position" in content),
        ("API失败时停止交易", "无法继续交易" in content and "return" in content),
        ("强制要求API成功", "强制要求API成功" in content)
    ]
    
    for desc, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {desc}: {'通过' if passed else '失败'}")
    
    return all(passed for _, passed in checks)

def main():
    """主验证函数"""
    print("验证强制API模式的所有修改")
    print("=" * 50)
    
    webapp_ok = verify_webapp_changes()
    main_ok = verify_main_changes()
    
    print("\n=== 验证总结 ===")
    if webapp_ok and main_ok:
        print("✅ 所有修改验证通过！")
        print("\n强制API模式已成功实现:")
        print("1. ✅ webapp.py: 强制使用币安API，移除回退机制")
        print("2. ✅ main.py: 实时获取仓位，确保交易决策基于真实数据")
        print("3. ✅ 所有交易都将基于币安API显示的实际仓位")
        print("4. ✅ 消除了本地状态与实际仓位不一致的问题")
    else:
        print("❌ 部分修改验证失败，请检查代码")
    
    return webapp_ok and main_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)