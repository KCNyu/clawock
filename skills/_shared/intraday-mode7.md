# Mode 7 — 盘中盯盘正文（cron，每 30 分钟；hk + us 共用，单一来源）

> 两个市场的盘中 cron 读的是同一份正文：cron 任务正文（`config/cron-payloads/intraday.md`）给出本档
> market（`hk` 或 `us`），下文 `{market}` 一律按它替换。`hk-stock-analysis` / `us-stock-analysis` 的
> Mode 7 只是指回这里的路由，规则只改这一份。
>
> 必读闭包：本文件、`skills/_shared/intraday-status-sidecar.md`（第 4 步写 sidecar 的规范）、Step 1 的核心包。
> 市场 SKILL 的 Modes 1–6、报告模板和其他 skill 不属于本任务，不用读。skills catalog 只是索引，
> 这两份正文要真的 `read` 进来才算加载。

当前 `config/intraday-delivery.json` 的 `always_full: true` 要求每档完整卡，无变化也正常发；以 preflight 本档 `delivery_mode` 为准。以下 `no_change` / `review_candidate` 静默分支仅在 operator 显式改为 false 时启用（权威契约见 `docs/architecture/intraday-agent.md`），不得自行切换。

## 市场差异

策略真源是本档核心包里的 `holding_policies` / `strategy_checks`，下面只列排程与写法上的差别。

- `hk`：港股 10:03–11:33、14:03–15:33 HKT。
- `us`：美股按 ET 交易日判定，含跨 HKT 午夜档。SPCH 无限子弹流：不重复风险提醒、不建议砍仓；仅 `raw_wechat_block` 本档新出现 P0 行时核 `strategy_checks` 的数值、状态和来源证据并问一次是否继续。策略由持仓 `strategy` 与 `config/intraday-strategy-policies.json` 表达。只有 `strategy_checks.status=clear` 才能说对应 P0 未触发；`unavailable` 只说证据未取到，不拿单日涨跌推断五交易日。

## 步骤

1. `clawock intraday preflight --market {market} --judgment-packet`。`market_closed` 结束。stdout 是核心包（计划含 0 股观察、观察线、`analyzer_block`、来源与失败状态），`index.references` 列出参考层条目（板块全景等），按条目的 fetch 命令取；同代副本留在 `memory/.tmp/intraday-context-{market}-latest.json`，postflight 用 `context_id` 锁同代。任何行情缺口按 `quote_coverage` 明说，不能把旧价说成实时。
2. `delivery_mode=no_change`：健康且语义未变，直接 `clawock intraday postflight --market {market} --context-id <id>`；postflight 记审计心跳并静默，不写散文/sidecar；若健康闸或发布闸失败，watchdog 仍兜底。`review_candidate` 只因新软候选唤醒：模型判断无需发时，prose 文件只写 `SILENT` 并带 `--text-file` 调 postflight，不写 sidecar；值得说则按 full_delta 写。`full_delta` 才必须写 `▎我的看法`，1–3 行：变化、判断；另起一行写 `下一触发：<标的> <条件><价位>；…`（标的写代码或恒指/恒科等指数名；价位只用该标的明确的 context 价位，或其本档现价 ±5% 内的前瞻位，不得借别票价格或股数；条目用「；」分隔。条目里除这个价位外不写别的数字：postflight 把条目中每个数字都当价位核对，「5 日低」「20 日高」里的 5、20 会被判成核对不上，这类说明写成「近期低点」「前高」。这条价位规则只写在这里，cron 任务正文与市场 SKILL 只引用；postflight 逐项核对标的与价位后把这一行放在判断上方，不写或核对不上会在卡片顶部标出）。先读 `semantic_delta`、`plan_triggers`、`anomalies`、一级事件，再看相关 `mover_news` / `peer_scan` / `add_side_reads`。三态都不是下单授权。`strategy_conflicts` 是旧计划与当前持仓策略的未解冲突，只据事实说明，不复述被策略禁止的旧减仓建议，也不擅自改写 risk_rule 为择时。只说相关票；旧计划、旧新闻和持仓表不复述。模型负责取舍和归因，消息短不等于删模型上下文；看完整 `plan_context`、`watch_levels` 与各来源失败状态（都在核心包里）。参考层按判断需要取，不必每档全取：要说同业/板块背离或轮动，取相关票的 `peer_scan`（要做全持仓比较才取整份）；要追溯持仓策略过滤前的信号或解释策略冲突，取 `source_signals_detail`（普通信号理由已在 `analyzer_block`）；要核对摘要里没有的来源、时间或原文，取 `information_full`；其余条目按具体判断取对应切片。没取的条目不当作已看过，也不据它下结论。这条取用规则只写在这里，cron 任务正文只引用。数值只引用包内原值（下一触发的前瞻位按上面这条价位规则），绝不心算差值、倍数、金额、股数或自行补状态/催化。`index.rule_outputs` 列出哪些字段是登记规则的结论（筛选、评分、候选），其余是观测：规则结论可以采纳也可以不同意，不同意时写依据。判断需要包内没有的量（另一个窗口、两只票的比值、相对强弱）时用 `clawock tool compute --arg 'expression=…'` 让系统在日线上算，原样引用返回值并说明它是什么；要看规则结论底下的原始日线/因子逐项/全部事件用 `clawock tool observations --arg ticker=<代码> --arg kind=bars|factors|events`。
字段 `add_side_reads.rows[].evidence.proxy_label` 表示 20 日高/位来自代理标的：07226 的代理为恒科指数，SPCH 的代理为 SPCX；不得把代理价位当成杠杆产品自身价格。`kind=left_scale_in` 是左侧观察档（kcn 2026-09-27，observe）：只照抄首档与失效位，不给尺寸，不得写成加仓建议、股数或「可以低吸」的授权。`peer_scan` 已由 preflight 提供全持仓板块全景（参考层，按 index 取）；不要另读 `peer-map.json`，不要另调 `clawock fetch-peers`。缺项需标明，不能用缓存价补。
候选生成不等于议程决定：`full_holdings` 含全持仓现价、日涨跌、报价新鲜度和计划触发线距离；`soft_candidates`、`opportunity_radar`、`early_trend_candidates`、`provisional_setups`、`t0_setups`、`semantic_state` 都是供你比较边缘机会和历史变化的材料；没有硬阈值命中也要看候选是否值得说。`known_catalysts` 衔接晨报，`active_information_candidates` 留一手来源与失败状态。
3. 对本档异动，优先用 `mover_news` 的一手 `interrupt`；`context` 只是背景，`no_recent_filing` 是窗口内无新公告，`degraded` 是源未取到。`plan_context.open` 只作动作约束，不能把 0 股持有观察写成待执行买卖。`add_side_reads` 的 candidate/wait/reject 三态都不是下单授权；有纪律冲突先说阻断条件。一级披露 `candidate|wait|reject` 也不是下单授权。
**异动归因**：`mover_news` 中 `tier=primary` 且 `signal=interrupt` 才可能是硬催化；`tier=supporting` 只能作背景；盘中模型禁止 Tavily——harness 已为每只异动票每个交易日检索一次，结果在 `anomaly_search`（每条带 grade 与 URL，引用写出处；`unavailable`/`empty` 是没查到，不等于没有消息）。`no_recent_filing` 写“窗口内无新一手公告”，`index_fund_no_issuer` 写“指数基金无发行人公告”（其 `items` 是按底层指数/主题匹配到的市场快讯，只作背景），`degraded` 写“催化源未取到”，不能把源失败说成无消息。`suppressed_noise` 等计数不要写进报告。只挑本档变化的最多两条，避免复述旧新闻。

4. `full_delta` 或 `review_candidate` 决定发送时，同时写 `memory/.tmp/intraday-prose-{market}.md` 和 `memory/.tmp/intraday-insights-{YYYY-MM-DD}.json`；sidecar 按第一轮已读的 `skills/_shared/intraday-status-sidecar.md` 写。调用 `clawock intraday postflight --market {market} --context-id <id> --text-file /root/.openclaw/workspace/memory/.tmp/intraday-prose-{market}.md`。harness 拼持仓表、验证、投递微信/TG、刷新 dashboard；不调用 message/send。postflight 不设超时，不在提交前终止。最终回复只留 status/投递/commit 结果，不复制消息。
