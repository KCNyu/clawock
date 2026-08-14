---
layout: default
title: clawock · 证据与反证
description: 我们测了什么、什么没通过。全部数字从产物读取，非手写。
---

# 证据与反证

面板展示的是结果。这一页展示的是**方法**——测了什么、什么没活下来、以及我们拒绝声称什么。

每个数字都在页面生成时从产物读出，没有一个是手打的：静态文案里的数字会悄悄过期，这一页是重新生成的。三种判定严格区分——**未通过**（测了，没活下来）、**尚不可判**（样本不够，还不能说）、**通过**。把前两者混为一谈本身就是一种不诚实。

## 杠杆刻度盘（生产 tier 映射）

**判定：🔴 未通过** · 样本：1370 根日线 · 2021-01-04 → 2026-07-31 · 来源：run card `regime_dial_validation-20260802-896b2145`

| | |
|---|---|
| 样本内改善（对比一直 2x） | -91.6% vs -95.5%，即 +3.9pp |
| 置换检验 p 值（回撤 / 收益） | 0.925 / 0.970 |
| 随机重排的中位改善 | 10.2% |
| 样本外 walk-forward | 2 / 4 折改善回撤，阈值不稳定 |
| 生产阈值在网格中的排名 | 13 / 16 |
| 各档触发占比 | green 30.5% · amber 59.5% · red 10.0% |

> 观测到的改善比**随机重排同一条敞口路径的中位数还差**（10.2%）。p = 0.925 是**未能拒绝原假设，不是证伪**——一个指数、一次崩盘，撑不起「没用」，正如它撑不起「有用」。刻度盘保留未改；不能再做的是拿另一个策略的数字当它的证据。

## 量化因子 edge

**判定：⚪ 尚不可判** · 样本：留痕 48 天 · 来源：`assets/data/quant_signal_review.json`

| | |
|---|---|
| `rsi_overbought_fade` | 命中率 28.6% · CI95 [0.0%, 100.0%] · n=7（6 日 × 3 标的）· ⚪ CI 跨 50%，锁定 |
| `rsi_oversold_bounce` | 命中率 64.3% · CI95 [33.3%, 100.0%] · n=28（18 日 × 8 标的）· ⚪ CI 跨 50%，锁定 |
| `stop_breach_continue` | 命中率 48.7% · CI95 [32.7%, 65.3%] · n=271（43 日 × 11 标的）· ⚪ CI 跨 50%，锁定 |
| `trend_off_avoid` | 命中率 47.0% · CI95 [33.6%, 59.4%] · n=328（43 日 × 10 标的）· ⚪ CI 跨 50%，锁定 |
| `trend_on_follow` | 命中率 5.6% · CI95 — · n=36（36 日 × 1 标的）· ⚪ 样本只覆盖单一簇，算不出聚类 CI —— 无法解读 |
| `zscore_extreme_revert` | 命中率 80.0% · CI95 [0.0%, 100.0%] · n=10（6 日 × 6 标的）· ⚪ CI 跨 50%，锁定 |

> 解锁规则是 `cluster_ci_entirely_above_or_below_50pct`：置信区间必须整体落在 50% 一侧。目前 0/6 个因子达标。**CI 跨 50% 是「样本还不够」，不是「因子无效」**——两者的处置相同（不入决策），结论不同。

## 截面因子（预注册）

**判定：⏳ 尚未到期** · 样本：预注册于 2026-07-26 · 来源：`assets/data/cross_sectional_factor.json`

| | |
|---|---|
| `prospective_dates` | 0 / 需要 24 · ⚪ 未达标 |
| `prospective_tickers` | 0 / 需要 12 · ⚪ 未达标 |
| `prospective_sectors` | 0 / 需要 3 · ⚪ 未达标 |
| `price_coverage` | 1.0 / 需要 0.8 · ✅ |
| `quality_coverage` | 0.0 / 需要 0.6 · ⚪ 未达标 |
| `clustered_edge` | None / 需要 CI lower > 0.0 · ⚪ 未达标 |
| `membership_history` | False / 需要 True · ⚪ 未达标 |
| `corporate_actions` | Tencent qfq forward-adjusted daily bars / 需要 adjusted · ✅ |

> **这不是一条没通过的检验，是还没到期。** 前瞻收益要 21 个交易日才算得出来，注册后的快照一条都还没满窗，所以计数必然是 0（最早可测 2026-08-24，按当前节奏最早 2026-09-24 才可能激活）。这一层只用 `registered_at` 之后记录的快照，回溯结果永远不能激活它——代价就是必须等，而等待和失败是两件事。

## 低频加仓交互（新 campaign）

**判定：⚪ 尚不可判** · 样本：factor 14 日 × information 14 日 · 来源：run card `add_alpha_walkforward-20260813-3a918d77`

| | |
|---|---|
| `US T1 interaction` | n=4 · mean 3.11% · hit 100.0% · collecting |
| `US T5 interaction` | n=4 · mean 4.13% · hit 75.0% · collecting |
| `US T20 interaction` | collecting · n=0（不显示为 0%） |
| `HK T1 interaction` | n=2 · mean 1.77% · hit 50.0% · collecting |
| `HK T5 interaction` | n=1 · mean -1.03% · hit 0.0% · collecting |
| `HK T20 interaction` | collecting · n=0（不显示为 0%） |
| 覆盖日期 | factor 14 · information 14 · overlap 12 |
| 前瞻信息日期 | 1 |
| authority 分类 | none 217 · exploration 7 · validated 0 |

> 价格相对强弱与点时信息必须共同出现；技术位只安排已经获准的 tranche。当前 run card 是 current-universe / legacy-news replay，且前瞻信息日期仍为 0，所以只用于收集与诊断，**不是 validated alpha**。旧账本里的 `add_only_on_trigger` 是 mixed/legacy 样本，不计作这套 campaign 的成绩。

---

<sub>由 `clawock evidence` 生成于 2026-08-14T04:03:01+08:00。数字全部读自产物；改动结论请改产物，不要改这一页。</sub>
