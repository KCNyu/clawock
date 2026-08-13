# USER.md - About Your Human

- **Name:** Shengyu Li
- **What to call them:** kcn
- **Pronouns:** _(to be learned)_
- **Timezone:** Asia/Shanghai (GMT+8)
- **Notes:** Chinese speaker, interested in stock analysis

## Context

- Primary interest: Stock market analysis and trading
- Communication: Comfortable with both Chinese and English
- Username: KCNyu (Telegram)

---

The more you know, the better you can help. But remember — you're learning about a person, not building a dossier. Respect the difference.

## 交易风格
- **风险偏好：激进型**
- **可用现金：约15万人民币（≈$20,500 USD）**
- 美股+港股持仓均在可接受范围内
- 不排斥高波动标的，可以接受较大回撤
- 港股AI个股（MiniMax、迅策等）有兴趣追热点
- **AI 板块是 alpha 来源** —— 智谱 / MINIMAX / 迅策 这类，新闻和南向资金敏感度高于其他板块

## 沟通偏好（来自历史日志归纳）

- **持仓回答统一用表格** —— 一句话验证："喜欢简洁表格展示持仓"（2026-05-13 备注）
- **直接判断，不要 hedging** —— 跳过 "this is not financial advice" 之类的免责，铁律已记录在 `MEMORY.md`
- **数据缺失必须明说** —— ⚠️ 标注哪条没拿到，禁止用旧数据兜底回答
- **terse 风格** —— 中英文都能接，少废话多结论，能用结构化展示就不用大段文字
- **盯盘节奏不止开/午/收** —— 14:00 HKT 盘中也会查（见 2026-05-14 日志），盘中 cron `*/30 10-11,14-15`（HK，错开开/午/午后/收报告）就是为这个

## 工作节奏

- 港股工作日 09:30-12:00 / 13:00-16:00（北京时间同）
- 美股工作日按 ET 09:30-16:00 折算（禁止写死北京时间，见 `MEMORY.md § 时区`）；当季精确档位见 `docs/operations/cron-schedules.md`
- 收盘后通常会自己写一篇 `memory/YYYY-MM-DD.md` 复盘（手写习惯，agent 不要自动生成）
- 操作发生后习惯立即 git commit，且按 type 前缀（`portfolio:` / `memory:` / `docs:`；代码走 PR，用 `fix:` / `feat:` / `refactor:`）

## 不要做的事

- 不要建议立保证金 / 借钱加杠杆 —— 现金管理偏稳，杠杆敞口已经在杠杆 ETF 里
- 不要每次都重复"高风险请注意"之类的免责
- 不要从 dated memory 恢复已删除脚本；只用 installed `clawock` 与 named `ops/*` 入口
- 不要在 group chat / 微信简报里加 emoji 烟花 —— 标题用 1 个 emoji，正文克制
