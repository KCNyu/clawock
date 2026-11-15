# Mode 6 report prose rules

Shared by the HK and US open/midday/afternoon/close report crons. The market
skill's Step 2 only writes the prose; these four rules decide what the prose
must contain and must not say. Edit here once, not in both market skills.

用 stdout 里的字段：`signal_count` / `anomalies` / `index_direction` / `needs_risk_section` / `peer_scan` / `plan_context`（盘前简报还没执行完的决策，见下）/ `mover_news`（异动票的一手催化）/ `mover_thesis`（异动票的 thesis 与红线）（板块 + 同业 Top 5 今日/5日涨跌 + 背离信号，板块全景段直接用它）/ `live_information`（每只持仓的实时公告与新闻：`summary.<票>` 每条照抄 `cite`，含发布时间与「盘中实时」/「开盘前旧闻」；`degraded` 里的源是没取到，写「X 未取到」，不等于没有消息）/ `quote_coverage`（`unrefreshed` 里的票本次没刷到行情，表里是上次的价与涨跌；`anomalies`/`plan_triggers` 里这些票带 `quote_fresh: false`）；`raw_wechat_block` 是给你参考数字用的，**不要抄进散文**。任何行情缺口按 `quote_coverage` 明说，不能把旧价说成本时段的数。

▎情绪面 里的**异动归因**（`anomalies` 非空时必写，最多 2 行，写在该段最前）：
- 每只异动票一行：「{票} {幅度}% ← {mover_news 里 signal=interrupt 的标题要点}（{age_minutes} 分钟前 / {来源的中文说法}）」。`source_class` 只用来选说法，不照抄：`exchange_filing`/`hkexnews_filing`→交易所公告，`sec_filing`/`sec_filing_mirror`/`sec_fulltext`→SEC 文件，`finnhub_filing`→公司公告（Finnhub），`market_flash`→市场快讯，其余取值同样换成中文。
- `halts` 命中该票 → 先写停牌（停牌原因用中文说 + 复牌时间，`reason_code` 不照抄）。
- `mover_thesis` 里该票有 `triggered`/`watch` 红线 → 追一句「触及红线：{required_action}」——**这是归因语境，不是操作许可**，动作由模型判断，遵守事实、可行性与已有授权；catalyst 评级只是登记策略意见。
- 没有 interrupt：`no_recent_filing` 先查 `known_catalysts[票]`；有则写「窗口内无新公告；沿用今早已知催化：…」，没有才写「窗口内无新公告，且无已知催化，暂无法归因」；`index_fund_no_issuer` 写「指数基金无发行人公告，看成分/板块」；`degraded` 写「催化源未取到」（**不等于「没有消息」**）。一律不许编理由。
- 空间不够时**先砍板块全景的细节，不砍归因**——一次异动没解释，比少列两个同业更贵。

🗣 **读者只看得到这条微信，看不到管线**：三段里不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`/`context_id`，也不描述你在按什么指令、格式或步骤写；约束翻成交易语言（「packet 锁定的破位审议线」→「计划里的破位复核线」）。postflight 会以 advisory 标出。
context 的字段名与枚举值（任何带下划线的英文标识，如 `hold_and_watch`、`near_breakout`，以及 `verdict=wait` 这类「键=值」）一律不写进正文，翻成中文说法（`hold_and_watch`→持有观察）；postflight 会把它标成正文顶部的校验警告。

**长度由你自己判断**：不设字数目标，把该说的说完，不为凑数注水也不为省字砍内容。
必须写到的：`peer_scan` 的 Top 5、持仓在同行里的位置、今日/5 日涨跌和归因、异动归因、
计划对账、三段必需标记、证据，以及 `needs_risk_section=true` 时的风险提示。
自然要避免的是重复而不是长度——同一组合风险数字不要在技术面、操作建议和风险提示三段
重复；财报/lockup 日期只在最相关的一段写一次；情绪面的异动归因和同行对比不要在技术面复述。
