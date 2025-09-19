# 交易策略说明（基于布林带的突破-回调+翻转）

本文档总结当前代码中的完整交易策略与执行链路，便于快速核对与排错。

## 一、总体架构与数据流
- 实时行情：通过 WebSocket 订阅 Binance K线流，解析为 KlineEvent 事件并回调策略处理。
- 数据持久化：K线与指标、信号、交易、错误、策略状态等均写入 SQLite。
- 指标计算：仅使用“已收盘”的K线计算布林带，保证与交易所一致。
- 策略决策：使用布林带上下轨的“突破-回调”逻辑生成信号；包含止损与持仓翻转机制。
- 交易执行：支持真实模式与模拟模式；开仓后可自动挂出止损单。
- Web 看板：展示账户/仓位、最新信号、交易明细、PNL统计与错误日志等。

## 二、指标与信号生成
- 指标计算
  - 指标窗口：window（默认20）。
  - 均值与标准差参数：boll_multiplier（默认2.0）、boll_ddof（默认0）。
  - 仅用 is_closed==True 的K线计算布林带；up=MA+mult*STD，dn=MA-mult*STD。
- 信号逻辑（收盘价 close 与上下轨 up/dn 比较）
  1) 触发“等待开仓”状态：
     - 突破上轨（close 从 ≤up 到 >up）：设置 breakout_up=True → pending=waiting_short_entry。
     - 跌破下轨（close 从 ≥dn 到 <dn）：设置 breakout_dn=True → pending=waiting_long_entry。
  2) 开仓（flat → 建仓）：
     - pending=waiting_short_entry 且 close 回到 ≤up → 开空 open_short。
     - pending=waiting_long_entry 且 close 回到 ≥dn → 开多 open_long。
  3) 持仓翻转：
     - 持有空仓：若后续“跌破下轨”→ pending=waiting_long_confirm；当 close 反弹回 ≥dn → 平空并开多 close_short_open_long。
     - 持有多仓：若后续“突破上轨”→ pending=waiting_short_confirm；当 close 回落至 ≤up → 平多并开空 close_long_open_short。
  4) 止损：
     - 空仓：close 再次 >up → 空仓止损 stop_loss_short（状态重置为 flat）。
     - 多仓：close 再次 <dn → 多仓止损 stop_loss_long（状态重置为 flat）。
- only_on_close：当 only_on_close=True 时，仅在K线收盘事件上评估策略，避免盘中反复触发。

## 三、执行与风控
- 资金与仓位
  - 下单数量：按“可用USDT×max_position_pct/价格”计算，并做精度截断（qty_precision）。
  - 杠杆：启动时设置 leverage（若配置了 API Key/Secret）。
- 下单与止损
  - 市价单开/平仓；翻转信号会先市价平当前方向，再按同样规则市价开反向仓位。
  - stop_loss_enabled=True 时，开仓后自动挂出 reduce-only STOP_MARKET 止损单（closePosition=true），触发价格按 entry_price±stop_loss_pct 计算，workingType 可配置（MARK_PRICE/CONTRACT_PRICE）。
- 实际仓位一致性
  - 每次决策前尝试从交易所查询真实仓位，若成功则用真实持仓覆盖本地状态，防止状态漂移。
- 状态持久化
  - 每个事件后保存 StrategyState（position/pending/entry_price/breakout_level、breakout_up/dn、last_close_price）。

## 四、数据库模型（SQLite）
- klines：K线（含 is_closed 标记）。
- indicators：每根已收盘K线的 MA/STD/UP/DN。
- signals：策略信号日志（时间、信号名、价格）。
- trades：交易记录（时间、方向、数量、价格、订单ID、状态）。
- errors：错误日志（时间、位置、信息）。
- strategy_state：策略状态的时间序列快照（可恢复最近状态）。

## 五、关键配置（.env 可覆盖）
- 基础：LOG_LEVEL、DB_PATH、TZ。
- 交易订阅：SYMBOL、INTERVAL、WINDOW、SIMULATE_TRADING。
- 风控：STOP_LOSS_PCT、MAX_POSITION_PCT、LEVERAGE、ONLY_ON_CLOSE、STOP_LOSS_ENABLED、STOP_LOSS_WORKING_TYPE、PRICE_ROUND、QTY_PRECISION。
- 指标：BOLL_MULTIPLIER、BOLL_DDOF、INDICATOR_MAX_ROWS。
- 网络：WS_PING_INTERVAL/WS_PING_TIMEOUT/WS_BACKOFF_*、RECV_WINDOW、HTTP_TIMEOUT、WS_BASE、REST_BASE。

## 六、真实模式与模拟模式
- 模拟模式（simulate_trading=True）：应当在无API Key时也能运行，记录“模拟成交”，用于开发/回测阶段。
- 真实模式：配置 API Key/Secret 后下真实单；开仓后自动挂止损（可关闭）。

## 七、已知问题与改进建议（需确认）
1) 模拟分支不可达（重要）
   - 现有流程在生成信号后先判断“若未提供 API Key/Secret 则直接 return”，导致无钥匙情况下无法进入“模拟交易”分支。
   - 建议：将“模拟交易分支”提前到 return 判断之前，或仅在真实交易分支判断 API Key/Secret。
2) 交易状态更新规则与实际不一致
   - update_trade_status_on_close 仅将状态为 'NEW' 的最近一笔开仓标记为 'OVER'，但模拟与真实模式记录的 status 通常为 'FILLED'，导致无法正确回溯关联开/平单。
   - 建议：
     - 要么将开仓订单统一标记为 'NEW'，成交后再更新；
     - 要么在更新时不限定 'NEW'，而是匹配最近的相关开仓方向记录。
3) 盘中触发的抖动风险
   - 当 only_on_close=False 时，close 价格在单根K线内波动会产生多次信号评估；虽然指标基于已收盘K线，但建议生产使用 only_on_close=True，以降低噪声。
4) pnl_percentage 字段
   - get_position_info 中从 API 取 pos['percentage'] 字段（可能不存在），通常会为0；如需显示真实回报率，建议用未实现盈亏/持仓名义价值推算。

## 八、策略是否“完善”的结论
- 策略核心逻辑（突破-回调开仓、突破回调翻转、上下轨止损）清晰、对称、并与布林带计算口径一致，整体设计合理。
- 但存在上述两处实现细节问题（模拟分支不可达、交易状态更新逻辑与实际状态值不匹配），建议尽快修正以保证测试与回溯数据的正确性。
- 如需进一步稳健：
  - 默认仅在收盘触发；
  - 为翻转与止损增加冷却/去重保护；
  - 在下单前再次核对实际仓位与最大可下单量（考虑保证金与最小下单步进）。

## 九、快速核对清单
- 指标：仅用已收盘K线计算；窗口、倍数、ddof 与配置一致。
- 信号：四类主信号（open_long/open_short/close_long_open_short/close_short_open_long）+ 两类止损。
- 执行：开仓后自动挂止损；翻转先平仓再开仓。
- 持久化：每事件保存策略状态；信号与交易均入库；错误日志可在网页端查看。
- 配置：.env 能覆盖全部关键参数；REST/WS 基础地址可自定义。