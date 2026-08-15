# 分析:为什么系统 8 月零加仓建议(2026-08-15)

> kcn 反馈:"为什么不说加仓,一直砍仓很不舒服,应该有很多机会可以入场"。
> 本文是数据诊断 + 修复方向,待 kcn 确认后落地。

## 〇、过去一周(08-10~08-14)运行状况

**头号问题:盘前简报 5 天里 4 天异常**

| 日期 | 早报 mtime | 情况 | 根因 |
|---|---|---|---|
| 08-10 周一 | 08:57 | 晚 ~57 分钟 | 慢/重试 |
| 08-11 周二 | **缺失** | brief+plan missing,远端 fallback dispatch,outcome unknown | 08:00 run error,consecutiveErrors 超预算不重试 |
| 08-12 周三 | **缺失** | 同上,fallback 也 "no workflow_dispatch run found" | 同上(rerun-onhost 排队未成功) |
| 08-13 周四 | 21:42 | **晚 13.5 小时**(当晚补跑成功) | 同上(rerun 队列最终跑通) |
| 08-14 周五 | 08:08 | ✅ 正常 | — |

- 根因链:08:00 cron run "ended in error" → openclaw runtime `consecutiveErrors past budget` 不再自动重试 → watchdog rerun-onhost 排队 → 远端 GH Actions fallback 也 15 分钟内没找到 dispatch → 早报缺失/巨晚。
- 与 #544(08-14 午后快报 Exec failed)同一类 **openclaw 工具层故障复发**(08-10 开盘 ×2 / 08-11 午后 / 08-12 早报 / 08-13 早报 / 08-14 午后)。
- heartbeat 佐证:08-10/08-11 盘中心跳 0 条(12 日起才恢复),那两天盘中监控同样缺失。

**其它运行问题**:
- 08-14 13:30 港股午后快报:postflight holder 发送中死亡,WeChat 未送达,watchdog 只兜底 Telegram(#544,已挂起观察)。
- 08-12 盘中 intraday-hk 一次 deterministic-fallback "openclaw is not installed"(环境类,单次)。
- 08-14 15:30 HK slot:delta 门把 regime 翻转判"无变化"压成回执(#546,已修)。

## 一、硬数据:加仓输出归零的时间线

| 月份 | add_only_on_trigger | cut | trim_on_rebound | hold_and_watch |
|---|---|---|---|---|
| 2026-05 | 9 | 17 | 16 | 36 |
| 2026-06 | 3 | 50 | 33 | 122 |
| 2026-07 | **23** | 108 | 27 | 105 |
| **2026-08** | **0** | 26 | 13 | 47 |

- 最后一批 add:2026-07-20(7/15~7/20 每天 5 条:03033 / 02208 / PLTR / RKLB / SPCX / MSFT)。
- **7/21 起 25 天零 add**,与 kcn 感受完全一致。
- 8 月 86 条决策 = 47 hold + 26 cut + 13 trim,**0 add**。

## 二、直接原因:四条 gate 全部堵死

以 2026-08-14 收盘数据实测:

1. **风险 gate**:10 个持仓里 7+ 挂着 breach(hard_stop ×4、single_name ×3、β、leveraged_exposure ×2、factor_concentration、regime_delever)。`_constraints` 对 risk 名字只允许 `[cut]` / `[trim_on_rebound, cut]`,`can_add=False` 硬堵。
2. **趋势 gate**:经典三条 setup(trend_pullback / confirmed_breakout / oversold_reclaim)全部要求 `trend_on`(close>MA200 且 MA50>MA200)。8 月 HK 趋势 OFF(HSTECH 4,792 < MA200 5,192,-7.7%)→ HK 全部名字 setup 全灭;US 只有 RKLB trend on 但 close 80.1 < 前高 86.83 不触发。
3. **超买 gate**:唯一在突破的名字 00100(8/13 close 376.8 > 前高 374.4)z=2.14 ≥ 2 → early_trend 判 `wait_pullback_rebreak`(等回踩),不给 add;CRCL 同理(z=2.52,trend off)。
4. **次新 gate**:SKHY(26 bars)<30-bar 门槛 → `compute_signals` 返回 None → technical 全 null → early_trend 永远 not_candidate;00100(146 bars)<200 → ma200=None → trend_on=None → 经典 setup 全灭。**#542(短历史降级)已修,8/15 ff-merge 后已生效,SKHY 首次可算**。

## 三、结构性问题:机会面 = 决策面

1. **决策面=持仓面**:系统只在持仓里做加减。`new_ideas=0`(8/13 简报自报)——智谱(02513)/迅策等 AI 新票不在 instruments / peer 池,entry-gate 是手动研究闸,不进 cron。
2. **LLM 散文 vs 决策账本脱节**:8/14 散文 Aggressive 档明确写了"03033 借 4.84 阻力位加仓 200 股吃南向资金"、"00100 借 5d high 388.6 trim 30 股",但 decisions.jsonl 同日 = 3 cut + 全 hold,零 add。**机会只活在散文里,决策/计划卡只有砍仓**——kcn 看到的就是"系统只会砍"。
3. **无换仓叙事**:砍 RKLX/SPCH 的弹药去向,系统只说 swap 1x(降杠杆),不接"腾弹药 → 候选名单"。
4. **用户行为与系统纪律对立**:kcn 实际在 SPCH 无限子弹流(7/22 起 buy ×10 次,240→260 股,8/15 还买),系统每天挂 "SPCH cut 200" risk_rule 单;kcn 8/4 加仓 00100 20 股,系统对 00100 输出 hold_and_watch + single_name breach。**系统没有"用户 override 风险纪律"的反馈通道**(8/13 撤销 SPCH 累计加仓成本 P0 是 MEMORY 级特批,没进 risk_rule 判定)。
5. **执行反馈循环**:7 月 23 次 add 建议 0 执行(not_followed/unknown)→ add 无 edge 数据 → 校准更保守;Brier 0.3366 > baseline 0.2644(校准不合格)→ 系统倾向 hold/cut。

## 四、当下(8/14 收盘)真实机会面

用新代码实测:

| 名字 | close | 前20d高 | 状态 | early_trend |
|---|---|---|---|---|
| SKHY | 166.33 | 177.93 | 距前高 7%,5d +20% 强势,26 bars 首次可算 | not_candidate(未突破)→ 突破 177.93 即 breakout |
| 00100 | 329.0 | 388.6 | 8/13 突破 374.4 后 8/14 暴跌 -13% 假突破 | wait_pullback_rebreak(等企稳再突破) |
| CRCL | 71.6 | 75.89 | 8/14 -5%,z 回 1.41 | 未突破 |
| RKLB | 80.25 | 86.83 | trend on 但未突破 | 未突破 |

诚实结论:8/14 大跌后当下无"突破中"的名字;但 8/13 明明有(00100 突破 + SKHY 强势),系统当时也只给 hold_and_watch——**机会存在但被压成看不见**。

## 五、修复方向(待 kcn 选择)

| # | 建议 | 类型 | 收益 |
|---|---|---|---|
| A | 部署验证 #542/#543(已生效,下周一盘中看 SKHY 候选行) | 已完成 | 次新候选可见 |
| B | **"机会雷达"输出节**:brief/盘中加"候选观察"(突破中 / 等回踩 z≥2 / 距前高<5% / 板块联动),只提示不下单 | 新功能 | 直接回应"为什么不说加仓" |
| C | **换仓配对**:cut/trim 决策自动带"弹药去向"候选(swap 语义显式化) | 新功能 | 砍完知道买什么 |
| D | **用户行为入账**:SPCH 无限子弹流 / 00100 加仓 → `risk confirm` override,系统停止每日重复喊 cut,降为周提醒 | 配置/流程 | 停止对立喊话 |
| E | AI 观察池:智谱 02513 / 迅策注册 instruments + peer 池(entry-gate 流程) | 研究 | 机会面扩到持仓外 |
| F | 散文加仓建议同步进 decisions.jsonl(03033 加仓 200 那种,落成 add_only_on_trigger) | 流程 | 决策账本与散文一致 |

## 六、给 kcn 的一句话

系统不是"不会说加仓",是**加仓被四条纪律 gate 堵死 + 机会只写在散文里没进决策账本 + 你的实际加仓行为(SPCH/00100)系统看不见**。前三条是市场+持仓现状(部分已修),后两条是可修的架构缺口。

## 七、修复方案设计(建议 B/C 落地 spec)

### 方案 B:机会雷达(候选观察节)

**目标**:brief + 盘中档增加"机会面"输出,让候选状态可见(不下单授权)。

**数据源**(全部已有,零新抓取):
- `quant_signals`(或盘中 `compute_signals`/`compute_short_history_signals` 实时):close / prior_20d_high / zscore20 / trend_on
- `early_trend.classify` 输出(state / observed / blockers)— #543 已接盘中
- `peer_residual.json`:residual_5d / dispersion_5d(板块联动证据)
- `news_evidence_graph.json`:信息确认状态

**渲染规则**(进 `raw_wechat_block`,additive-only,无候选时逐字节不变——沿用 #543 的 `append_early_trend_section` 模式):

| 状态 | 行文案 |
|---|---|
| 突破中(close>前高 且 z<2) | `◆ [突破] 00100 现价 X / 前高 Y, z Z —— 突破确认,可评估入场` |
| 等回踩(close>前高 且 z≥2) | `◆ [等回踩] 00100 现价 X / 前高 Y, z Z —— 超买,回踩再突破可入场` |
| 接近突破(距前高<5% 且 z<2) | `◆ [接近] SKHY 距前高 7% —— 突破 Y 即 breakout` |
| 板块联动 | `◆ [联动] SKHY 5d +20% · HBM 链 MU/STX 同步` |

**语义边界**(写进 SKILL.md):候选≠下单;只有 `add_only_on_trigger` 决策才是授权;机会雷达只回答"机会在哪",不回答"现在买"。

### 方案 C:换仓配对(砍仓弹药去向)

**目标**:系统输出 cut/trim 时,自动附带"弹药去向"候选,把"砍"变成"换"。

**规则**:
- 每次 cut/trim 决策生成时,从机会雷达候选中挑 1-2 个同腿(同市场)候选作为 `reinvest_candidates` 字段挂进 decision。
- 弹药的量级 = cut 市值 × 0.5(半仓试错,不强制全换)。
- 对应名字有 risk 时降级为"观察",不配对。
- 散文必须出现一句"砍 RKLX 的 ~$240 弹药 → 候选:SKHY(突破 Y 触发)/00100(等回踩)"这类话术。

### 方案 D:用户行为入账(override 通道)

- `clawock mark-followed DECISION_ID --no` 已有;扩展一个 `clawock override-risk --ticker SPCH --reason "无限子弹流"` 命令:写入 `memory/risk_breaches.json` 的 `overridden` 状态 + `decisions.jsonl` 的 `execution.overridden_by_user`。
- override 后:该名字的 risk_rule cut 从"每日重复挂单"降为"每周提醒";breach 账本标记 `acknowledged_by_user`。
- kcn 的 SPCH/00100 已发生加仓 → 一次性把历史行为标记进去,停止对立喊话。

### 优先级

1. **D(行为入账)** — 最便宜、立刻停止"每天喊砍你不理"的对立;SPCH 是最大痛点。
2. **B(机会雷达)** — 直接回应"为什么不说加仓",1-2 个 PR 能落地(#543 已铺好渲染模式)。
3. **C(换仓配对)** — 依赖 B 的候选列表,紧随其后。
4. **E(智谱/迅策入池)** — 研究流程,需 entry-gate 走一遍。
5. **F(散文→账本同步)** — 提示词层面约束,需观察 LLM 行为。

## 八、仓库优化扫描(代码/配置/测试)

### P1(值得修)

| 位置 | 问题 | 建议 |
|---|---|---|
| `config/add-alpha-policy.json` vs `packet.py:428-469` | **配置漂移:sizing 覆盖层 10 个 key 全缺**——`factor_top_multiplier` / `peer_leader_multiplier` / `information_positive_multiplier` / `maximum_combined_multiplier` 等全部落到 `policy.get(key, default)` 硬编码默认,改 config 无效 | 把 10 个 key 补进 config(或确认默认值后删掉 packet 里的 fallback 以强制 config 权威) |
| `market_data/peer_residuals.py` | **无直接测试**——它是 early_trend / add_alpha 的核心输入(00100/SKHY 的 residual_leader 全靠它),出 bug 会静默改变候选判断 | 补单元测试(至少覆盖 live 行解析 + 最小 peer 数闸) |
| `harness/intraday_preflight.py` | **无直接测试文件**(仅 test_intraday_delta_gate 间接跑 main)——18 slot/天的核心路径 | 补测试(collect_provisional_setups fail-soft / render 逐字节一致) |

### P2(可选)

| 位置 | 问题 | 建议 |
|---|---|---|
| 39 个模块读 `portfolio.json`(`publish/dashboard.py` 24 处 / `artifacts.py` 10 处) | 重复读文件、无缓存,`read_text` 无 mtime 检查 | 加进程级缓存或统一 load 层(带 freshness) |
| `harness/brief_preflight.py` / `report_postflight.py` | 与 #544 同源的 "Exec failed" 复发(08-10×2/08-11/08-12/08-13/08-14),postflight 后模型用 exec 读临时文件触发 | SKILL.md/提示词加"postflight 后禁止 exec 读 .tmp 确认送达"铁律(与盘中 slot 对齐) |
| `docs/` + README | 8/13 批量合并 #501/#505/#523 后,`docs/reference/commands.md` 与 skill 路由是否同步待核 | 跑一次 docs 生成器 + system_check 确认无漂移 |

### 已确认健康项

- 无裸 `except: pass`;全量测试 2060+ 通过;#546/#542/#543 三 PR 已 merge 且 editable install 已生效(SKHY 首次可算已实测)。
- openclaw gateway `/health` live;watchdog 兜底链路(Telegram 镜像/远端 fallback/rerun-onhost)都在工作——早报缺失是"上游 cron error 不重试",不是兜底没接。

## 九、附:SPCH/00100 用户行为数据(方案 D 依据)

- **SPCH**:21 笔买入、累计 ≈ $3,585、现 260 股、成本 12.51、浮亏 -28%——超过已撤销的 $3,000 纪律线,kcn 无限子弹流行为明确。
- **00100**:6 笔买入、累计 ≈ ¥66,370、现 120 股、HK book 58.7%(single_name breach 27d)。
