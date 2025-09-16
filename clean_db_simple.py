import sqlite3

conn = sqlite3.connect('trader.db')
cursor = conn.cursor()

# 检查当前数据量
cursor.execute('SELECT COUNT(*) FROM klines')
kline_count = cursor.fetchone()[0]
print(f'当前K线数据条数: {kline_count}')

cursor.execute('SELECT COUNT(*) FROM indicators')
indicator_count = cursor.fetchone()[0]
print(f'当前指标数据条数: {indicator_count}')

# 清理数据
cursor.execute('DELETE FROM klines')
kline_deleted = cursor.rowcount
cursor.execute('DELETE FROM indicators')
indicator_deleted = cursor.rowcount

conn.commit()
print(f'已删除 {kline_deleted} 条K线数据')
print(f'已删除 {indicator_deleted} 条指标数据')

# 验证清理结果
cursor.execute('SELECT COUNT(*) FROM klines')
remaining_klines = cursor.fetchone()[0]
cursor.execute('SELECT COUNT(*) FROM indicators')
remaining_indicators = cursor.fetchone()[0]

print(f'清理后K线数据条数: {remaining_klines}')
print(f'清理后指标数据条数: {remaining_indicators}')

conn.close()
print('数据库清理完成！')