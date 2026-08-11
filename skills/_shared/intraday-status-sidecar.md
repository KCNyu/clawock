# 共享规范：intraday 状态横幅 sidecar（hk + us Mode 7 Step 2.5 共用，单一来源）

> 抽出来避免 hk/us 两个 SKILL 各写一份导致 drift（2026-05-31）。两边 Mode 7 的
> Step 2.5 只放一个指针 + 本市场杠杆 ticker 例子，规范以本文件为准。

`build_dashboard` 读它刷新 dashboard **顶部状态横幅** + **Today's Movers 每条归因**（缺失/解析失败容错，横幅自动隐藏；非关键，漏写不影响 WeChat 报告投递）。**只输出文本，绝不写任何 key。**

写 `memory/.tmp/intraday-insights-{YYYY-MM-DD}.json`：
```json
{
  "status_banner": "一句话 ≤50字：regime + 今日盈亏主来源 + 最该盯的一件事（盯盘提醒口吻）",
  "movers": {"代码": "一行归因 ≤40字：催化 / 板块beta / 纯杠杆放大噪音 + 操作含义(追/不追/观望)"}
}
```
- **模型只写 `status_banner` / `movers` 文本**；`generated_at` 由 postflight harness
  以当前真实 UTC 写入，禁止模型生成或猜测基础设施时间。
- `movers` 覆盖 context 里 `anomalies` / today_movers 的**每个**票；**杠杆 ETF 要点明"杠杆放大"、区分标的真涨还是纯 beta**（本市场杠杆 ticker 见调用方 Step 2.5）。
- **催化优先引 `context.mover_news`**：该票有 `signal=interrupt` 的条目就用它的标题要点 + `age_minutes` 写归因；`halts` 命中先写停牌；`no_recent_filing` / `index_fund_no_issuer` / `degraded` 各自照实说（分别是「无一手公告」「指数基金无发行人」「催化源未取到」）。
- **只用 context.json 的真实数字**；不确定催化就写"无明确个股催化，纯 beta"，**不编造财报/新闻**。
- HK / US 两个 intraday 共写这**同一个** per-date 文件，build_dashboard 取最新 mtime（当前在盘的市场覆盖横幅）。
