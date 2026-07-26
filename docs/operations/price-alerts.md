# 价格提醒运行说明

## 当前在用的系统（2026-05 起）

价格提醒**已迁移到 cron-driven market report / intraday harness**，不再由
`price_alert_monitor.py` 持续轮询。

触发链路：
1. 运行态共有 **11 个 OpenClaw cron job**；以 `openclaw cron list --json` 为准，
   受版本控制的 schedule/payload 契约见 `config/cron-schedules.json`，人读表见
   `docs/operations/cron-schedules.md`
2. 开盘/午盘/收盘报告走 Mode 6；高频盘中任务走 Mode 7 harness
3. 分析输出直接标注 STOP / TRIM / BUY / WATCH 信号；信号聚合后追加风险提示
4. 唯一微信路径是 `openclaw-weixin`，同一结果同步镜像到 Telegram
5. Mode 7 每个预期 slot 都写 heartbeat，CI 和 watchdog 可区分成功、失败、漏跑与运行中

**入口 skill**：`hk-stock-analysis` / `us-stock-analysis` 的 **Mode 6（报告）**与
**Mode 7（盘中 harness）**

## 想加自定义提醒怎么做

不要再去改 `price_alert_monitor.py`。两个推荐路径：

### A. 临时盯单只股（一次性）
直接跟 Rick 说："盯下 RKLB，到 73 提醒我"。Rick 会用 Mode 1/2 + 后续 check-in 跟进。

### B. 持续提醒（多日）
1. 在 `portfolio.json` 对应 ticker 加 `alert_above` / `alert_below` 字段
2. 扩展 `analyze_{hk,us}_stocks.py` 在 wechat report 里读这些字段并打信号
3. 不重新启用 `price_alert_monitor.py` — 那是上一代轮询架构，不符合现在
   cron + harness + heartbeat 的设计

## 已废弃

- `price_alert_monitor.py` — 2 个月没运行（monitor_state 最后更新 2026-03-19，无 cron）。代码里硬编码了 NVDA/QQQ 等已清仓 ticker，重新启用前必须清理
- `monitor_state.json` — 上一代状态文件，停摆同一天
- `monitor.log` — 同上，停摆于 2026-03-19

## 历史

2026-03 之前用 `price_alert_monitor.py` 每分钟轮询 + Telegram 通知。
2026-05-05 用户清理了 07709/07747 持仓，price_alert_monitor.py 同时移除两条提醒，但脚本本身没启动新进程。
2026-05 起统一走 cron 报告路径；后续盘中链路升级为 harness，并加入 Telegram
镜像、watchdog 与逐 slot heartbeat。本文件保留旧轮询迁移背景，同时描述当前入口。
